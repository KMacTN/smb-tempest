#!/usr/bin/env python3
################################################################################
# Script: smb_tempest_ctl.py
# Purpose: Orchestrates multi-client distributed SMB load tests using
#          smb_tempest.py across multiple remote systems via SSH.
#
# Author: KMac and Sheila
# Date:   April 30, 2025
#
# Description:
# ------------
# - Reads a list of target clients (username, IP, TEMPEST_BASE) from a configuration file
# - Connects via SSH to each client and launches smb_tempest.py
# - Collects and stores logs from each client
# - Aggregates test results for centralized reporting
#
# Example Usage:
# --------------
# python smb_tempest_ctl.py \
#     --clients clients.conf \
#     --ssh_key ~/.ssh/id_rsa \
#     --server_ip nucleus \
#     --share_name tempest \
#     --share_username admin \
#     --share_password PASSWORD \
#     --num_tasks 1000 \
#     --max_file_size 10
################################################################################

import paramiko
import asyncio
import argparse
import os
import time
from concurrent.futures import ThreadPoolExecutor

# Read clients from a file
def load_clients(filename):
    clients = []
    with open(filename, "r") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#'):
                parts = line.split()
                if len(parts) == 3:
                    username, ip, tempest_base = parts
                    clients.append((username, ip, tempest_base))
    return clients

# Connect to a single client and start smb_tempest.py
async def launch_test_on_client(client_info, args):
    username, client, tempest_base = client_info
    print(f"Connecting to {client} as {username}...")
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    ssh_kwargs = {
        "hostname": client,
        "username": username,
        "allow_agent": True,
        "look_for_keys": True
    }
    if args.ssh_key:
        ssh_kwargs["key_filename"] = args.ssh_key

    ssh.connect(**ssh_kwargs)

    venv_activate = f"{tempest_base}/smb_tempest_env/bin/activate"
    smb_tempest_path = f"{tempest_base}/smb_tempest.py"

    remote_cmd_parts = []
    remote_cmd_parts.append(f"source {venv_activate}")
    remote_cmd_parts.append(
        f"python3 {smb_tempest_path} "
        f"--server_ip {args.server_ip} "
        f"--share_name {args.share_name} "
        f"--username {args.share_username} "
        f"--password {args.share_password} "
        f"--num_tasks {args.num_tasks} "
        f"--max_file_size {args.max_file_size}"
    )

    cmd = " && ".join(remote_cmd_parts)

    stdin, stdout, stderr = ssh.exec_command(cmd)

    out = stdout.read().decode()
    err = stderr.read().decode()

    log_dir = "client_logs"
    os.makedirs(log_dir, exist_ok=True)

    with open(os.path.join(log_dir, f"{client.replace('.', '_')}_stdout.log"), "w") as f:
        f.write(out)
    with open(os.path.join(log_dir, f"{client.replace('.', '_')}_stderr.log"), "w") as f:
        f.write(err)

    ssh.close()
    print(f"Finished {client}")

# Orchestrate all clients
async def main():
    parser = argparse.ArgumentParser(description="Tempest Coordinator for Multi-Client SMB Load Test")
    parser.add_argument("--clients", required=True, help="Path to clients.conf (format: username ip TEMPEST_BASE)")
    parser.add_argument("--ssh_key", required=False, help="Path to SSH private key (optional if agent is used)")
    parser.add_argument("--server_ip", required=True, help="Target SMB server IP")
    parser.add_argument("--share_name", required=True, help="SMB share name")
    parser.add_argument("--share_username", required=True, help="Username for SMB server")
    parser.add_argument("--share_password", required=True, help="Password for SMB server")
    parser.add_argument("--num_tasks", type=int, required=True, help="Number of tasks per client")
    parser.add_argument("--max_file_size", type=int, default=10, help="Max file size (MiB)")
    args = parser.parse_args()

    clients = load_clients(args.clients)

    if not clients:
        print("❌ No valid clients found in clients.conf. Exiting.")
        exit(1)

    tasks = []
    executor = ThreadPoolExecutor(max_workers=len(clients))
    loop = asyncio.get_event_loop()

    for client_info in clients:
        tasks.append(loop.run_in_executor(executor, asyncio.run, launch_test_on_client(client_info, args)))

    await asyncio.gather(*tasks)

if __name__ == "__main__":
    asyncio.run(main())
