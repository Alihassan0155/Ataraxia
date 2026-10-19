"""Opt-in real PostgreSQL security regressions. LOCALHOST ONLY; no .env access."""
import json,os,unittest,uuid
from pathlib import Path
import psycopg
from psycopg import sql
from backend.onboarding.repository import PreferenceRepository,InvalidInterests

MIGRATION=Path('backend/migrations/003_user_interest_preferences.sql')
DEFAULTS=Path('backend/reports/migration003_production_20261019/default_privileges.json')
PRIVILEGES=('SELECT','INSERT','UPDATE','DELETE','TRUNCATE','REFERENCES','TRIGGER','MAINTAIN')

@unittest.skipUnless(os.getenv('ATARAXIA_LOCAL_SECURITY_TESTS')=='1','Opt-in localhost PostgreSQL security tests')
class MigrationSecurityTests(unittest.TestCase):
    reports=[]
    def setUp(self):
        self.database='ataraxia_m003_security_'+uuid.uuid4().hex[:8]
        with self.connection('postgres') as c:
            self.assertEqual(str(c.execute('SELECT inet_server_addr()').fetchone()[0]),'127.0.0.1')
            c.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(self.database)))
        self.a,self.b=uuid.uuid4(),uuid.uuid4()
        with self.connection() as c:
            self.assertTrue(c.execute("SELECT rolbypassrls FROM pg_roles WHERE rolname='service_role'").fetchone()[0])
            c.execute('CREATE SCHEMA auth');c.execute('CREATE TABLE auth.users(id uuid PRIMARY KEY)')
            c.execute("CREATE FUNCTION auth.uid() RETURNS uuid LANGUAGE sql STABLE AS $$SELECT nullif(current_setting('request.jwt.claim.sub',true),'')::uuid$$")
            c.execute('GRANT USAGE ON SCHEMA auth TO authenticated')
            c.execute('CREATE TABLE public.interest_categories(id text PRIMARY KEY,name text NOT NULL,taxonomy_version text NOT NULL,is_onboarding boolean NOT NULL)')
            c.execute("INSERT INTO public.interest_categories VALUES('a','Interest A','test-v1',true),('b','Interest B','test-v1',true),('u','unknown','test-v1',false)")
            c.execute('GRANT SELECT ON public.interest_categories TO service_role')
            c.execute('INSERT INTO auth.users VALUES(%s),(%s)',(self.a,self.b))
            # These default ACL changes exist ONLY in this disposable database,
            # after fixture creation. No cluster roles or production ACLs change.
            for creator,schema,kind,role,privilege in json.loads(DEFAULTS.read_text())['default_table_privileges']:
                self.assertEqual((creator,schema,kind),('postgres','public','r'))
                self.assertIn(privilege,PRIVILEGES)
                c.execute(sql.SQL('ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public GRANT {} ON TABLES TO {}').format(sql.SQL(privilege),sql.Identifier(role)))
        self.before=self.inventory()

    def connection(self,database=None,role=None):
        c=psycopg.connect(host='127.0.0.1',port=55439,user='postgres',dbname=database or self.database,autocommit=True)
        if role:c.execute(sql.SQL('SET ROLE {}').format(sql.Identifier(role)))
        return c

    def inventory(self):
        with self.connection() as c:
            return {'defaults':c.execute('SELECT defaclrole,defaclnamespace,defaclobjtype,defaclacl::text FROM pg_default_acl ORDER BY 1,2,3').fetchall(),
                    'categories':c.execute('SELECT * FROM interest_categories ORDER BY id').fetchall(),
                    'users':c.execute('SELECT id FROM auth.users ORDER BY id').fetchall(),
                    'category_acl':c.execute("SELECT relacl::text,relrowsecurity FROM pg_class WHERE oid='public.interest_categories'::regclass").fetchone(),
                    'uid_function':c.execute("SELECT pg_get_functiondef(oid),proacl::text,prosecdef FROM pg_proc WHERE oid='auth.uid()'::regprocedure").fetchone(),
                    'public_relations':c.execute("SELECT relname,relkind FROM pg_class WHERE relnamespace='public'::regnamespace ORDER BY 1").fetchall(),
                    'public_functions':c.execute("SELECT proname FROM pg_proc WHERE pronamespace='public'::regnamespace ORDER BY 1").fetchall(),
                    'parent_triggers':c.execute("SELECT tgrelid::regclass::text,tgname FROM pg_trigger WHERE tgrelid IN ('auth.users'::regclass,'public.interest_categories'::regclass) ORDER BY 1,2").fetchall()}

    def apply(self,text=None):
        with self.connection() as c:c.execute(text or MIGRATION.read_text(encoding='utf-8-sig'))
    def seed(self):
        with self.connection() as c:c.execute("INSERT INTO user_interest_preferences(user_id,category_id) VALUES(%s,'a'),(%s,'b')",(self.a,self.b))
    def denied(self,role,query,params=None):
        with self.connection(role=role) as c:
            with self.assertRaises(psycopg.errors.InsufficientPrivilege):c.execute(query,params)

    def test_legacy_grants_reproduce_cross_user_truncate(self):
        text=MIGRATION.read_text(encoding='utf-8-sig').split('-- Fail closed')[0]+'COMMIT;'
        text=text.replace('FROM PUBLIC,anon,authenticated,service_role;','FROM PUBLIC,anon;')
        self.apply(text);self.seed()
        with self.connection(role='authenticated') as c:c.execute('TRUNCATE public.user_interest_preferences')
        with self.connection() as c:self.assertEqual(c.execute('SELECT count(*) FROM user_interest_preferences').fetchone()[0],0)

    def test_exact_effective_privilege_matrix_and_truncate_denied(self):
        self.apply();self.seed()
        expected={'anon':set(),'authenticated':{'SELECT'},'service_role':{'SELECT','INSERT','DELETE'}}
        actual={}
        with self.connection() as c:
            for role,allowed in expected.items():
                actual[role]={p for p in PRIVILEGES if c.execute("SELECT has_table_privilege(%s,'public.user_interest_preferences',%s)",(role,p)).fetchone()[0]}
                self.assertEqual(actual[role],allowed)
            for role in expected:
                for column in ('user_id','category_id','created_at'):
                    self.assertEqual(c.execute("SELECT has_column_privilege(%s,'public.user_interest_preferences',%s,'UPDATE')",(role,column)).fetchone()[0],role=='service_role' and column=='category_id')
        for role in expected:self.denied(role,'TRUNCATE public.user_interest_preferences')
        with self.connection() as c:self.assertEqual(c.execute('SELECT count(*) FROM user_interest_preferences').fetchone()[0],2)
        self.reports.append({'database':self.database,'effective_permissions':{k:sorted(v) for k,v in actual.items()},'service_column_update':['category_id']})

    def test_rls_and_denied_client_writes(self):
        self.apply();self.seed()
        for user,other in [(self.a,self.b),(self.b,self.a)]:
            with self.connection(role='authenticated') as c:
                c.execute("SELECT set_config('request.jwt.claim.sub',%s,false)",(str(user),))
                self.assertEqual(c.execute('SELECT user_id FROM user_interest_preferences').fetchall(),[(user,)])
                self.assertEqual(c.execute('SELECT * FROM user_interest_preferences WHERE user_id=%s',(other,)).fetchall(),[])
        with self.connection(role='authenticated') as c:self.assertEqual(c.execute('SELECT * FROM user_interest_preferences').fetchall(),[])
        self.denied('anon','SELECT * FROM user_interest_preferences')
        for role in ['anon','authenticated']:
            self.denied(role,'DELETE FROM user_interest_preferences WHERE user_id=%s',(self.b,))
            self.denied(role,"UPDATE user_interest_preferences SET category_id='a' WHERE user_id=%s",(self.b,))
            self.denied(role,"INSERT INTO user_interest_preferences(user_id,category_id) VALUES(%s,'a')",(self.b,))

    def test_service_operations_idempotence_and_isolation(self):
        self.apply();self.seed()
        repo=PreferenceRepository(lambda:self.connection(role='service_role'))
        repo.replace(self.a,['a','b'])
        with self.connection() as c:before=c.execute('SELECT * FROM user_interest_preferences ORDER BY user_id,category_id').fetchall()
        repo.replace(self.a,['b','a'])
        with self.connection() as c:self.assertEqual(c.execute('SELECT * FROM user_interest_preferences ORDER BY user_id,category_id').fetchall(),before)
        for invalid in [['u'],['nonexistent'],['a','a']]:
            with self.assertRaises(InvalidInterests):repo.replace(self.a,invalid)
        self.assertEqual({r['id'] for r in repo.preferences(self.a)},{'a','b'})
        repo.replace(self.a,[]);self.assertEqual(repo.preferences(self.a),[]);self.assertEqual([r['id'] for r in repo.preferences(self.b)],['b'])

    def test_migration_error_rolls_back_schema_grants_and_triggers(self):
        text=MIGRATION.read_text(encoding='utf-8-sig').rsplit('COMMIT;',1)[0]+"DO $$ BEGIN RAISE EXCEPTION 'injected migration failure'; END $$; COMMIT;"
        with self.connection() as c:
            with self.assertRaises(psycopg.errors.RaiseException):c.execute(text)
            c.execute('ROLLBACK')
        self.assertEqual(self.inventory(),self.before)

    def test_privilege_guard_aborts_excess_access_atomically(self):
        text=MIGRATION.read_text(encoding='utf-8-sig').replace('-- Fail closed','GRANT TRUNCATE ON public.user_interest_preferences TO authenticated;\n-- Fail closed',1)
        with self.connection() as c:
            with self.assertRaises(psycopg.errors.RaiseException):c.execute(text)
            c.execute('ROLLBACK')
        self.assertEqual(self.inventory(),self.before)

    def test_only_expected_objects_and_existing_permissions_unchanged(self):
        self.apply();after=self.inventory()
        for key in ['defaults','categories','users','category_acl','uid_function','public_functions']:self.assertEqual(after[key],self.before[key])
        new=set(after['public_relations'])-set(self.before['public_relations'])
        self.assertEqual(new,{('user_interest_preferences','r'),('user_interest_preferences_pkey','i')})
        with self.connection() as c:
            self.assertEqual(c.execute("SELECT relrowsecurity FROM pg_class WHERE oid='public.user_interest_preferences'::regclass").fetchone(),(True,))
            constraints=c.execute("SELECT contype,convalidated FROM pg_constraint WHERE conrelid='public.user_interest_preferences'::regclass").fetchall()
            self.assertEqual(sorted(constraints),[('f',True),('f',True),('p',True)])
            self.assertEqual(c.execute("SELECT policyname,cmd,roles::text FROM pg_policies WHERE tablename='user_interest_preferences'").fetchall(),[('preferences_read_own','SELECT','{authenticated}')])
            self.assertFalse(c.execute("SELECT EXISTS(SELECT 1 FROM pg_class WHERE relnamespace='public'::regnamespace AND relkind='S')").fetchone()[0])
        self.assertTrue(all(name.startswith('RI_ConstraintTrigger_') for relation,name in after['parent_triggers']))

    @classmethod
    def tearDownClass(cls):
        out=Path('backend/reports/migration003_security_20261019');out.mkdir(exist_ok=True)
        (out/'privilege_evidence.json').write_text(json.dumps(cls.reports,indent=2),encoding='utf-8')
