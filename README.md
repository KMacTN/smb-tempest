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

## 🛠 Preparing a System to Use `smb_tempest.py`

Follow these steps to clone the `smbgen` repository and prepare your system for running `smb_tempest.py`.

---

### 1. Clone the Repository

> **Note:** You must be granted access to the repo and have GitHub SSH authentication set up.

---

#### a. Configure Your SSH Agent for GitHub Access

Create or edit your SSH config file:

```bash
vi ~/.ssh/config
```

Add the following block:

```ssh
Host github.com
    HostName github.com
    User git
    IdentityFile ~/.ssh/github_sshkey_rsa
    IdentitiesOnly yes
```

Ensure the private key exists and has correct permissions:

```bash
ls -1 ~/.ssh/github_sshkey_rsa*
/home/ubuntu/.ssh/github_sshkey_rsa
/home/ubuntu/.ssh/github_sshkey_rsa.pub
```

> Remember to save the SSH private key (`IdentityFile`) and set file permissions to `0400`.

---

#### b. Add Your SSH Key and Start the Agent

Start the agent and add your key:

```bash
eval "$(ssh-agent -s)"
ssh-add ~/.ssh/github_sshkey_rsa
```

You should see:

```
Agent pid 1607
Enter passphrase for /home/ubuntu/.ssh/github_sshkey_rsa:
Identity added: /home/ubuntu/.ssh/github_sshkey_rsa (user@kmactn.com)
```

---

#### c. Test the Connection

You can test your setup by running:

```bash
ssh -i ~/.ssh/github_sshkey_rsa -T git@github.com
```

Expected output:

```
Enter passphrase for key '/home/ubuntu/.ssh/github_sshkey_rsa': ****************
Hi KMacTN! You've successfully authenticated, but GitHub does not provide shell access.
```

> *(This is probably the one time you actually used a passphrase.)*

---

#### d. Clone the Repository

Finally, clone the repository:

```bash
git clone git@github.com:KMacTN/smbgen.git
```

Expected output:

```
Cloning into 'smbgen'...
remote: Enumerating objects: 116, done.
remote: Counting objects: 100% (116/116), done.
remote: Compressing objects: 100% (85/85), done.
remote: Total 116 (delta 60), reused 82 (delta 30), pack-reused 0
Receiving objects: 100% (116/116), 2.64 MiB | 54.05 MiB/s, done.
Resolving deltas: 100% (60/60), done.
```