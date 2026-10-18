"""Transactional repository for an existing Supabase PostgreSQL database."""
from .config import TABLES


REQUIRED = {
    'videos': {'video_id','content_hash','payload','title','language','source_dataset','source_id',
               'duration_seconds','orientation','media_uri','media_sha256','availability'},
    'processing_runs': {'id','content_hash','payload','kind','name'},
    'video_context': {'id','video_id','content_hash','payload','transcript','acoustic_features'},
    'affect_annotations': {'id','video_id','run_id','content_hash','payload','model','valence','arousal',
                          'recovery_suitability','emotions','dominant_emotion','confidence'},
    'video_semantics': {'id','video_id','run_id','context_id','affect_id','content_hash','payload',
                        'primary_category','semantic_summary','topics','tags'},
    'video_embeddings': {'id','video_id','run_id','semantic_id','content_hash','payload','embedding',
                         'model','revision','template_version','input_hash'},
    'processing_jobs': {'id','video_id','run_id','content_hash','payload','stage','status','attempts'},
    'interest_categories': {'id','content_hash','payload','taxonomy_version','name','aliases','subcategories','is_onboarding'},
}


def inspect_schema(conn):
    """Catalog/bucket metadata only, explicitly read-only; no video row reads."""
    with conn.transaction():
        with conn.cursor() as cur:
            cur.execute('SET TRANSACTION READ ONLY')
            cur.execute("""SELECT table_schema,table_name,column_name,data_type,udt_schema,udt_name
                           FROM information_schema.columns
                           WHERE table_schema NOT IN ('pg_catalog','information_schema')
                           ORDER BY table_schema,table_name,ordinal_position""")
            columns = [{'schema':r[0],'table':r[1],'column':r[2],'type':r[3],
                        'type_schema':r[4],'type_name':r[5]} for r in cur.fetchall()]
            cur.execute("""SELECT n.nspname,c.relname,a.attname,format_type(a.atttypid,a.atttypmod)
                           FROM pg_attribute a JOIN pg_class c ON c.oid=a.attrelid
                           JOIN pg_namespace n ON n.oid=c.relnamespace
                           WHERE a.attnum>0 AND NOT a.attisdropped AND c.relkind IN ('r','p')
                           AND n.nspname NOT IN ('pg_catalog','information_schema')""")
            types = [{'schema':r[0],'table':r[1],'column':r[2],'format':r[3]} for r in cur.fetchall()]
            cur.execute("""SELECT n.nspname,c.relname,con.contype,pg_get_constraintdef(con.oid)
                           FROM pg_constraint con JOIN pg_class c ON c.oid=con.conrelid
                           JOIN pg_namespace n ON n.oid=c.relnamespace
                           WHERE n.nspname NOT IN ('pg_catalog','information_schema')""")
            constraints = [{'schema':r[0],'table':r[1],'kind':r[2],'definition':r[3]} for r in cur.fetchall()]
            cur.execute("SELECT e.extname,n.nspname,e.extversion FROM pg_extension e JOIN pg_namespace n ON n.oid=e.extnamespace")
            extensions = [{'name':r[0],'schema':r[1],'version':r[2]} for r in cur.fetchall()]
            buckets = []
            if any(c['schema']=='storage' and c['table']=='buckets' for c in columns):
                cur.execute('SELECT id,name,public FROM storage.buckets ORDER BY id')
                buckets = [{'id':r[0],'name':r[1],'public':r[2]} for r in cur.fetchall()]
    return {'columns':columns,'types':types,'constraints':constraints,'extensions':extensions,'storage_buckets':buckets}


def compatibility(inventory, schema, mapping):
    missing = {}
    for logical, required in REQUIRED.items():
        actual = {c['column'] for c in inventory['columns'] if c['schema']==schema and c['table']==mapping[logical]}
        if required-actual:
            missing[logical] = sorted(required-actual)
    vector = next((t for t in inventory['types'] if t['schema']==schema and
                   t['table']==mapping['video_embeddings'] and t['column']=='embedding'), None)
    if vector is None or vector['format'].split('.')[-1] != 'vector(1024)':
        missing.setdefault('video_embeddings', []).append('embedding must be pgvector vector(1024)')
    if not any(e['name']=='vector' for e in inventory.get('extensions', [])):
        missing.setdefault('video_embeddings', []).append('pgvector extension required')
    # Retry-safe conflicts require a unique PRIMARY KEY matching the importer key.
    for logical in TABLES:
        key = 'video_id' if logical=='videos' else 'id'
        if not any(c['schema']==schema and c['table']==mapping[logical] and c['kind']=='p'
                   and c['definition']==f'PRIMARY KEY ({key})' for c in inventory['constraints']):
            missing.setdefault(logical, []).append(f'PRIMARY KEY ({key}) required')
    return {'compatible':not missing, 'missing_or_incompatible':missing,
            'note':'Review equivalent differently named tables before applying any migration.'}


class Repository:
    def __init__(self, conn, schema='public', mapping=None):
        self.conn, self.schema = conn, schema
        self.mapping = {name:name for name in TABLES}
        if mapping:
            if set(mapping)-set(TABLES) or any(not isinstance(v,str) for v in mapping.values()):
                raise ValueError('Invalid logical table mapping')
            self.mapping.update(mapping)
        inventory = inspect_schema(conn)
        # The clean catalogue deliberately retains only one current version. A
        # historical scan must never repopulate it after an approved replacement.
        # The view is installed only by the separately reviewed catalogue SQL.
        if any(c['schema']==schema and c['table']=='video_catalogue_current'
               for c in inventory['columns']):
            raise ValueError('Clean catalogue is active: legacy historical sync is disabled. '
                             'Use sync --current-only to prepare a reviewed catalogue delta.')
        report = compatibility(inventory,schema,self.mapping)
        if not report['compatible']:
            raise ValueError('Existing database schema is incompatible; run inspect and review schema_report.json first')
        self.vector_schema = next(e['schema'] for e in inventory['extensions'] if e['name']=='vector')

    def put_bundle(self, entities):
        counts = {'inserted':0,'updated':0,'skipped':0}
        with self.conn.transaction():
            with self.conn.cursor() as cursor:
                for item in entities:
                    state = self._put(cursor,item)
                    counts[state] += 1
        return counts

    def _put(self, cursor, item):
        from psycopg import sql
        from psycopg.types.json import Jsonb
        logical = item['table']
        if logical not in self.mapping:
            raise ValueError('Unknown logical table')
        table = sql.Identifier(self.schema,self.mapping[logical])
        key_name = 'video_id' if logical=='videos' else 'id'
        cursor.execute(sql.SQL('SELECT content_hash FROM {} WHERE {}=%s').format(table,sql.Identifier(key_name)),(item['key'],))
        prior = cursor.fetchone()
        if prior and prior[0]==item['content_hash']:
            return 'skipped'
        if prior and logical!='videos':
            raise ValueError('Immutable record ID collision; existing version preserved')
        columns = {key_name:item['key'], 'content_hash':item['content_hash'],
                   'payload':Jsonb(item['payload']), **item['columns']}
        values, placeholders = [], []
        for name, value in columns.items():
            if name=='embedding':
                # PostgreSQL casts into the installed vector extension namespace.
                values.append('['+','.join(str(float(v)) for v in value)+']')
                placeholders.append(sql.SQL('%s::{}').format(sql.Identifier(self.vector_schema,'vector')))
            else:
                values.append(Jsonb(value) if isinstance(value,(dict,list)) else value)
                placeholders.append(sql.SQL('%s'))
        query = sql.SQL('INSERT INTO {} ({}) VALUES ({}) ON CONFLICT ({}) ').format(
            table,sql.SQL(',').join(map(sql.Identifier,columns)),sql.SQL(',').join(placeholders),sql.Identifier(key_name))
        if logical=='videos':
            # Evaluate protection against the locked conflict row, not the earlier
            # SELECT: a concurrent storage update must also survive this upsert.
            protected = sql.SQL("({}.availability='s3_verified' AND left({}.media_uri,5)='s3://')").format(table,table)
            updates = []
            for k in columns:
                if k==key_name:
                    continue
                if k in ('media_uri','availability'):
                    value=sql.SQL('CASE WHEN {} THEN {}.{} ELSE EXCLUDED.{} END').format(
                        protected,table,sql.Identifier(k),sql.Identifier(k))
                elif k=='media_sha256':
                    # Different bytes cannot inherit a verified object's location.
                    value=sql.SQL('CASE WHEN {} THEN {}.{} ELSE EXCLUDED.{} END').format(
                        protected,table,sql.Identifier(k),sql.Identifier(k))
                else:
                    value=sql.SQL('EXCLUDED.{}').format(sql.Identifier(k))
                updates.append(sql.SQL('{}={}').format(sql.Identifier(k),value))
            # A content change requires explicit storage reconciliation, not a
            # silently stale verified location or mismatched metadata payload.
            cursor.execute(sql.SQL('SELECT media_sha256,availability,media_uri FROM {} WHERE video_id=%s FOR UPDATE').format(table),(item['key'],))
            storage=cursor.fetchone()
            if storage and storage[1]=='s3_verified' and (storage[2] or '').startswith('s3://') and storage[0]!=columns.get('media_sha256'):
                raise ValueError('Verified S3 media hash changed; reconcile storage explicitly')
            query += sql.SQL('DO UPDATE SET {}').format(sql.SQL(',').join(updates))
            query += sql.SQL(' WHERE NOT {} OR {}.media_sha256 IS NOT DISTINCT FROM EXCLUDED.media_sha256').format(protected,table)
        else:
            query += sql.SQL('DO NOTHING')
        cursor.execute(query,values)
        # Protect against simultaneous imports with a conflicting immutable payload.
        cursor.execute(sql.SQL('SELECT content_hash FROM {} WHERE {}=%s').format(table,sql.Identifier(key_name)),(item['key'],))
        actual = cursor.fetchone()
        if not actual or actual[0]!=item['content_hash']:
            raise ValueError('Concurrent immutable conflict; transaction rolled back')
        return 'updated' if prior else 'inserted'
