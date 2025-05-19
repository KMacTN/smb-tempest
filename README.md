## 📌 Overview

**smb_tempest.py** is _not_ a load testing or stress benchmarking tool. Its purpose is narrowly focused:

> **🎯 Goal:** Find the maximum number of active SMB sessions an SMB server can handle before rejecting new connections.

This project was designed to simulate realistic SMB session behavior — not to saturate bandwidth or stress IOPS. For proper storage benchmarking, use tools like [FIO](https://github.com/axboe/fio).

---

## ⚡ Quick Start

```bash
git clone git@github.com:KMacTN/smbgen.git
cd smbgen
bash setup_smb_tempest_env.sh
source smb_tempest_env/bin/activate
python smb_tempest.py --mode_streaming_reads
```

> 🧪 Example config files for various SMB testing workflows can be found in:
>
> [**example_configs.json**](./smb_tempest_examples_with_comments.json)

> 🔽 **See the [Setup Instructions](#-setup-instructions) section below for full installation details.** 

---


## 🗂️ Available Workload Modes

Each mode simulates one of the basic I/O workload profiles:

- `--mode_streaming_reads`: Large, sequential reads (e.g. media workloads)
- `--mode_read_iops`: Small, fast read operations to measure session IOPS
- `--mode_streaming_writes`: Large, sequential write operations
- `--mode_random_io`: Random mix of read/write I/O (read ratio configurable)

Example:

```bash
python smb_tempest.py --mode_streaming_reads --config my_test_config.json
```

To see all available options:

```bash
python smb_tempest.py --help
```

---

## 📁 Example Config Files

Sample JSON configurations are bundled in:

```text
smb_tempest_examples_with_comments.json
```

Each config includes a `_comment` key to describe its purpose. For example:

```json
{
  "_comment": "Random IOPS test: 90% reads, 10% writes",
  "smb_server_address": "10.0.2.173",
  "share_name": "smb-sessions",
  ...
}
```

---

## 🧰 Setup Instructions

To prepare your system, run the environment setup script:

```bash
bash setup_smb_tempest_env.sh
```

If Python’s venv module is missing, the script will prompt you to install it (e.g., `python3.12-venv`).

> ✅ Once setup completes, activate the virtual environment:
>
> ```bash
> source smb_tempest_env/bin/activate
> ```

> ❗ **Important:** If you log out or start a new terminal, you’ll need to re-run `source smb_tempest_env/bin/activate`.

---

## 🧪 Preparing a System to Use `smb_tempest.py`

Follow these steps to clone the `smbgen` repository and prepare your system for running `smb_tempest.py`.

---

### 1. Clone the Repository

> **🔐 Note:** Access to the private GitHub repo is required. To request access, contact [kmac@qumulo.com](mailto:kmac@qumulo.com).

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

> Remember to name the SSH private key to match the `IdentityFile` above, and set the file permissions to `0400`.

---

#### b. Add Your SSH Key and Start the Agent

Start the agent and add your key:

```bash
eval "$(ssh-agent -s)"
ssh-add ~/.ssh/github_sshkey_rsa
```

You should see something like:

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

> **FYI:**  
> 🔐 You probably used an actual ssh passphrase this one time.  
> 🧠 Rare. Wise. Effective. Bravo.

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

---

## 🧠 Understanding the Script

`smb_tempest.py` is a multi-threaded SMB session generator designed to:

- Create N simultaneous SMB client sessions to a target server
- Launch various I/O patterns (depending on the `--mode` selected)
- Report on session creation success, errors, throughput, and termination behavior

It supports multiple test modes:
- `--mode_streaming_reads`
- `--mode_read_iops`
- `--mode_streaming_writes`
- `--mode_random_io`

---


## 🧼 Cleaning Up

- Press `Ctrl+C` to stop any running test
- Check output logs if enabled
- Monitor system resource usage to determine when SMB session limits are hit

---