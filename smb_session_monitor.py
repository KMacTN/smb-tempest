#!/usr/bin/env python3
################################################################################
# Script: smb_session_monitor.py
# Purpose: Monitor active and inactive SMB sessions on a Qumulo cluster.
# Author: KMac | kmac@qumulo.com
# Date:   April 29, 2025
#
# Usage:
#   python3 smb_session_monitor.py --ip <cluster_ip> --username <user> --password <pass> [--threshold <seconds>] [--interval <seconds>] [--verbose]
#
# Description:
#   Connects to the Qumulo REST API and retrieves current SMB sessions.
#   Reports total, active, and inactive sessions based on idle time.
#   Supports verbose mode for detailed session output, including user and session ID.
################################################################################

import argparse
import qumulo
from qumulo.rest_client import RestClient
import requests
import time
import datetime

class bcolors:
    HEADER = '\033[95m'
    OKBLUE = '\033[94m'
    OKCYAN = '\033[96m'
    OKGREEN = '\033[92m'
    WARNING = '\033[93m'
    FAIL = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'
    UNDERLINE = '\033[4m'

def get_smb_session_counts(qumulo_ip, username, password, threshold_seconds=60, verbose=False):
    try:
        client = RestClient(qumulo_ip, 8000)
        client.login(username, password)
        response = client.request("GET", "/v1/smb/sessions/")
        sessions = response['session_infos']

        active_sessions = 0
        inactive_sessions = 0

        print(f"{bcolors.OKBLUE}Total sessions returned by API: {len(sessions)}{bcolors.ENDC}")

        for idx, session in enumerate(sessions):
            idle_nanoseconds = int(session.get('time_idle', {}).get('nanoseconds', 0))
            idle_seconds = idle_nanoseconds / 1e9
            user_info = session.get('user', {})
            username = user_info.get('name', 'N/A')
            sid = session.get('location', 'N/A')

            if idx < 1:
                print(f"Sample session object:\n{session}")
                print("Session keys:", session.keys())

            if idle_seconds <= threshold_seconds:
                active_sessions += 1
                status = f"{bcolors.OKGREEN}ACTIVE{bcolors.ENDC}"
            else:
                inactive_sessions += 1
                status = f"{bcolors.WARNING}INACTIVE{bcolors.ENDC}"

            if verbose:
                print(f"  [{idx+1:>4}] User: {username:<20} Session ID: {sid:<20} Idle: {idle_seconds:.1f}s Status: {status}")

        return active_sessions, inactive_sessions

    except requests.exceptions.ConnectionError as e:
        return f"{bcolors.FAIL}Error: Could not connect to Qumulo cluster. Check IP or network. {e}{bcolors.ENDC}"
    except qumulo.rest_client.RestClient.Error as e:
        return f"{bcolors.FAIL}Error: Qumulo API error: {e}{bcolors.ENDC}"
    except Exception as e:
        return f"{bcolors.FAIL}Error: An unexpected error occurred: {e}{bcolors.ENDC}"

def main():
    parser = argparse.ArgumentParser(description="Monitor active/inactive SMB sessions on Qumulo.")
    parser.add_argument("--ip", required=True, help="Qumulo cluster IP or hostname")
    parser.add_argument("--username", required=True, help="Qumulo API username")
    parser.add_argument("--password", required=True, help="Qumulo API password")
    parser.add_argument("--threshold", type=int, default=60, help="Idle time threshold in seconds (default: 60)")
    parser.add_argument("--interval", type=int, default=5, help="Polling interval in seconds (default: 5)")
    parser.add_argument("--verbose", action="store_true", help="Print all session details each poll")
    args = parser.parse_args()

    try:
        print(f"{bcolors.BOLD}{'Timestamp':<25} {'Active':<10} {'Inactive':<10}{bcolors.ENDC}")
        while True:
            timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            session_counts = get_smb_session_counts(
                args.ip,
                args.username,
                args.password,
                args.threshold,
                verbose=args.verbose
            )

            if isinstance(session_counts, str):
                print(f"{timestamp:<25} {session_counts}")
            else:
                active_count, inactive_count = session_counts
                print(f"{timestamp:<25} {bcolors.OKGREEN}{active_count:<10}{bcolors.ENDC} {bcolors.WARNING}{inactive_count:<10}{bcolors.ENDC}")

            time.sleep(args.interval)

    except KeyboardInterrupt:
        print("\nMonitoring stopped.")

if __name__ == "__main__":
    main()
