"""Verify all downloaded Drive files and map the untouched CSV to native media."""
import csv
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path
import av

ROOT = Path(__file__).resolve().parents[1]
FOLDER = ROOT / 'data/youtube_shorts_drive'


def main():
    listing = json.loads((FOLDER / 'drive_file_listing.json').read_text())['files']
    metadata_path = FOLDER / 'metadata/youtube_shorts_master.csv'
    with metadata_path.open(encoding='utf-8-sig', newline='') as handle:
        metadata = list(csv.DictReader(handle))
    results = {}
    with (FOLDER / 'download_status.jsonl').open(encoding='utf-8') as handle:
        for line in handle:
            result = json.loads(line)
            results[result['id']] = result
    names = defaultdict(list)
    inventory = []
    for entry in listing:
        result = results.get(entry['id'], {})
        assert result.get('status') in {'downloaded', 'already_present'}, entry['title']
        path = ROOT / result['path']
        assert path.is_file() and path.stat().st_size == int(entry['size']), entry['title']
        with av.open(str(path)) as container:
            assert container.streams.video, entry['title']
            frame = next(container.decode(video=0), None)
            assert frame is not None and not frame.is_corrupt, entry['title']
        record = {'drive_file_id': entry['id'], 'filename': entry['title'],
                  'file_path': path.relative_to(ROOT).as_posix(), 'size_bytes': path.stat().st_size,
                  'sha256': result.get('sha256', ''), 'first_video_frame_decoded': True}
        names[entry['title']].append(record)
        inventory.append(record)
    assert len({r['drive_file_id'] for r in inventory}) == len(listing)
    assert len(list((FOLDER / 'videos').rglob('*.mp4'))) == len(listing)
    assert len({r['video_id'] for r in metadata}) == len(metadata)
    mapped = []
    expected_names = {r['video_id'] + '.mp4' for r in metadata}
    for row in metadata:
        matching = names.get(row['video_id'] + '.mp4', [])
        assert matching, row['video_id']
        main_file = next((r for r in matching if '/duplicate_drive_files/' not in r['file_path']), None)
        assert main_file, row['video_id']
        assert int(row['file_size_bytes']) == main_file['size_bytes'], row['video_id']
        mapped.append({**row, 'original_file_path': row['file_path'], 'file_path': main_file['file_path'],
                       'drive_file_id': main_file['drive_file_id'], 'all_drive_file_ids': json.dumps([r['drive_file_id'] for r in matching]),
                       'media_sha256': main_file['sha256'], 'metadata_size_matches': True})
    for filename, records in names.items():
        if len(records) > 1:
            assert len({r['sha256'] for r in records}) == 1 and records[0]['sha256'], filename
    for filename, rows in [('video_inventory.csv', inventory), ('mapped_metadata.csv', mapped)]:
        with (FOLDER / filename).open('w', encoding='utf-8', newline='') as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
            writer.writeheader(); writer.writerows(rows)
    summary = {'drive_video_files': len(listing), 'downloaded_video_files': len(inventory),
               'unique_video_filenames': len(names), 'metadata_rows': len(metadata),
               'mapped_metadata_rows': len(mapped), 'missing_metadata_videos': 0,
               'unmapped_drive_filenames': sorted(set(names) - expected_names),
               'duplicate_filename_groups': {k: v for k, v in names.items() if len(v) > 1},
               'total_downloaded_bytes': sum(r['size_bytes'] for r in inventory),
               'first_frame_decode_passed': len(inventory),
               'metadata_sha256': hashlib.sha256(metadata_path.read_bytes()).hexdigest(),
               'category_distribution': dict(Counter(r['category'] or 'Unassigned' for r in metadata)),
               'note': 'All individual Drive files preserved, including identical duplicate-name copies. No ZIP used. First-frame verification is not full decoding or language validation. Historical transfer failures remain in the append-only log; the latest result for every video is successful.'}
    (FOLDER / 'download_verification.json').write_text(json.dumps(summary, indent=2) + '\n', encoding='utf-8')
    (FOLDER / 'download_report.md').write_text(
        '# Google Drive YouTube Shorts download\n\n'
        f"Downloaded {len(inventory)} individual videos from Ataraxia Youtube Shorts/videos. "
        f"The untouched metadata CSV has {len(metadata)} unique IDs, all matched to local files with matching sizes.\n\n"
        'Two filenames occur twice on Drive: p0fJtA8tJQs.mp4 and AyFgFQQ9APQ.mp4. '
        'Their SHA-256 values match within each pair. Additional copies are preserved under videos/duplicate_drive_files/<Drive file ID>/.\n\n'
        'metadata/youtube_shorts_master.csv is the downloaded source. mapped_metadata.csv supplies corrected local paths, Drive IDs, hashes and original path values. video_inventory.csv accounts for every Drive file. '
        'download_verification.json records the final successful verification; download_status.jsonl preserves transfer/retry history. transfer_summary.json describes the initial queue and predates the successful standalone retry.\n\n'
        'All video files passed first-frame decoding. Full media and language audits remain separate. Original datasets, normalization snapshots and active audits were not overwritten.\n', encoding='utf-8')
    print(json.dumps({k: v for k, v in summary.items() if k != 'duplicate_filename_groups'}, indent=2))


if __name__ == '__main__':
    main()
