# Google Drive YouTube Shorts download

Downloaded 762 individual videos from Ataraxia Youtube Shorts/videos. The untouched metadata CSV has 760 unique IDs, all matched to local files with matching sizes.

Two filenames occur twice on Drive: p0fJtA8tJQs.mp4 and AyFgFQQ9APQ.mp4. Their SHA-256 values match within each pair. Additional copies are preserved under videos/duplicate_drive_files/<Drive file ID>/.

metadata/youtube_shorts_master.csv is the downloaded source. mapped_metadata.csv supplies corrected local paths, Drive IDs, hashes and original path values. video_inventory.csv accounts for every Drive file. download_verification.json records the final successful verification; download_status.jsonl preserves transfer/retry history. transfer_summary.json describes the initial queue and predates the successful standalone retry.

All video files passed first-frame decoding. Full media and language audits remain separate. Original datasets, normalization snapshots and active audits were not overwritten.
