# Common File Signatures (Magic Bytes)

Magic bytes are clues, not proof that a file is safe or valid. Extensions and MIME labels can be misleading. Never execute an unknown file to identify it.

| Format | Typical leading bytes |
|---|---|
| PDF | %PDF- |
| PNG | 89 50 4E 47 0D 0A 1A 0A |
| JPEG | FF D8 FF |
| GIF | GIF87a or GIF89a |
| ZIP-based | 50 4B 03 04 |
| ELF | 7F 45 4C 46 |
| Windows PE/DOS | 4D 5A (MZ) |
| SQLite | SQLite format 3 |
| GZIP | 1F 8B 08 |
| RAR | 52 61 72 21 |
| 7-Zip | 37 7A BC AF 27 1C |
| OLE compound | D0 CF 11 E0 A1 B1 1A E1 |
| Android DEX | dex followed by a version |

The Field Kit reports a small set of signatures. Use a specialist parser and validate the complete structure for professional analysis.
