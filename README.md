# SMB Tempest

**Author:** KMac and Sheila  
**Updated:** May 18, 2025

## Overview

`SMB Tempest` is a multi-threaded SMB session generator and load tester.

It connects to an SMB share, creates client-specific directories, writes large files, performs sequential reads, churns random files, and measures performance — all concurrently across many simulated sessions.

## Key Features

- Multi-threaded SMB I/O stress testing
- Configurable block size, file size, session count, and I/O mix
- Rich operational modes (sequential, IOPS, streaming, and mixed)
- JSON-based config file with CLI override
- ASCII-friendly summary with throughput and IOPS
- Designed for scale testing SMB clusters and NAS environments

## Supported Modes

| Mode                  | Description                                                                 |
|-----------------------|-----------------------------------------------------------------------------|
| `--mode_streaming_reads`  | Read an existing file sequentially using large blocks (default 1MB)         |
| `--mode_read_iops`        | Perform many 4KB reads from offset 0 (default: 1024 reads)                  |
| `--mode_streaming_writes` | Write a large file using large blocks (default 1MB)                         |
| `--mode_random_io`        | Mix of random reads and writes on an existing file, guided by read percentage |

If **no mode is specified**, the tool defaults to:

> `default (write stream → read stream → churn small random files)`

This mode creates a file, reads it, then rapidly creates and deletes thousands of small files.

## Configuration

You can use a config file (`smb_tempest_cfg.json`) instead of CLI options. If the file exists and no `--config_file` is specified, you'll be prompted to use it.

### Sample Config File

```json
{
  "smb_server_address": "10.1.62.40",
  "share_name": "tempest",
  "username": "admin",
  "password": "Admin123!",
  "num_smb_sessions": 100,
  "max_file_size": 512,
  "block_size": 1048576,
  "mode_read_iops": true,
  "num_iops_reads": 2048,
  "fail_fast": true
}
```

For `--mode_random_io`, you must also include:

```json
"max_random_io_readpct": 70
```

## CLI Usage

```bash
# Run with explicit CLI args
python smb_tempest.py \
  --smb_server_address 10.1.62.40 \
  --share_name tempest \
  --username admin \
  --password Admin123! \
  --num_smb_sessions 125 \
  --mode_streaming_reads

# OR run using config file (if prompted)
python smb_tempest.py
```

## Output Example

```
==================== SMB Tempest Configuration ====================
Target SMB Server     : 10.0.2.173
Share Name            : smb-sessions
Username              : admin
Block Size            : 1.00 MB
Max File Size         : 1024 MiB
Number of Sessions    : 125
Mode                  : default (write stream → read stream → churn small random files)
Client UUID Directory : 4cfef4f8-2e23-4cba-8858-846e9fa8995c
====================================================================

Starting test...

....................................................................

================== Test Summary ==================
Test Mode(s) Used          : streaming_reads
Total Tasks Executed       : 125
Total Random Files Created : 0
Total Read/IO Volume       : 7.81 GB
Total Time Taken           : 18.20 seconds
Max Throughput Achieved    : 429.00 MB/s
Max IOPS Achieved          : 109,824 IOPS
==================================================
✅ SMB Tempest complete.
```

## Requirements

- Python 3.8+
- `smbprotocol` library
- Network access to the SMB server

Install dependencies:

```bash
pip install smbprotocol
```

## License

MIT License — use and modify freely.
