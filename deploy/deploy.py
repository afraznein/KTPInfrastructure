#!/usr/bin/env python3
"""
KTP Deployment Script

Deploys KTP game server components to production and test clusters
using SSH/SFTP via Paramiko.

Usage:
    python deploy.py --cluster atlanta --version 20260127
    python deploy.py --all --component plugins --version 20260127
    python deploy.py --cluster denver --profile lan --version 20260127

Environment Variables:
    Credentials can be set via environment variables instead of config.yaml.
    Format: KTP_<CLUSTER>_<FIELD> (e.g., KTP_ATLANTA_HOST, KTP_ATLANTA_PASSWORD)
    See .env.example for full list.
"""

import argparse
import json
import os
import sys
import datetime
import urllib.request
import urllib.error
from pathlib import Path
from typing import Dict, List, Optional

import paramiko
import yaml
from jinja2 import Environment, FileSystemLoader


def load_dotenv(env_path: Path) -> None:
    """Load environment variables from .env file if it exists."""
    if not env_path.exists():
        return

    with open(env_path, "r") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key, value = line.split("=", 1)
                key = key.strip()
                value = value.strip().strip('"').strip("'")
                if key and value:
                    os.environ.setdefault(key, value)


class KTPDeployer:
    """Handles deployment of KTP components to game servers."""

    def __init__(self, config_path: str, artifacts_dir: str, version: str):
        self.artifacts_dir = Path(artifacts_dir)
        self.version = version

        # Load .env file if present
        env_path = Path(__file__).parent / ".env"
        load_dotenv(env_path)

        self.config = self._load_config(config_path)
        self.template_env = None

        # Set up Jinja2 for config templates
        templates_dir = Path(__file__).parent / "templates"
        if templates_dir.exists():
            self.template_env = Environment(loader=FileSystemLoader(str(templates_dir)))

    def _load_config(self, config_path: str) -> dict:
        """Load configuration from YAML file and apply environment overrides."""
        with open(config_path, "r") as f:
            config = yaml.safe_load(f)

        # Apply environment variable overrides for cluster credentials
        # Format: KTP_<CLUSTER>_<FIELD> (e.g., KTP_ATLANTA_HOST)
        for cluster_name, cluster_config in config.get("clusters", {}).items():
            env_prefix = f"KTP_{cluster_name.upper()}_"

            # Check for host override
            env_host = os.environ.get(f"{env_prefix}HOST")
            if env_host:
                cluster_config["host"] = env_host

            # Check for user override
            env_user = os.environ.get(f"{env_prefix}USER")
            if env_user:
                cluster_config["user"] = env_user

            # Check for password override
            env_password = os.environ.get(f"{env_prefix}PASSWORD")
            if env_password:
                cluster_config["password"] = env_password

        # Apply data server IP if set
        data_server_ip = os.environ.get("KTP_DATA_SERVER_IP")
        if data_server_ip:
            config["data_server_ip"] = data_server_ip

        # Apply Discord relay settings from environment
        discord_relay_url = os.environ.get("KTP_DISCORD_RELAY_URL")
        if discord_relay_url:
            config["discord_relay_url"] = discord_relay_url
        discord_relay_secret = os.environ.get("KTP_DISCORD_RELAY_SECRET")
        if discord_relay_secret:
            config["discord_relay_secret"] = discord_relay_secret
        discord_channel_id = os.environ.get("KTP_DISCORD_CHANNEL_ID")
        if discord_channel_id:
            config["discord_channel_id"] = discord_channel_id

        return config

    def send_discord_notification(
        self,
        success: bool,
        clusters: List[str],
        components: List[str],
        errors: List[str] = None,
    ) -> bool:
        """Send deployment notification to Discord via relay."""
        relay_url = self.config.get("discord_relay_url")
        relay_secret = self.config.get("discord_relay_secret")
        channel_id = self.config.get("discord_channel_id")

        if not relay_url or not relay_secret or not channel_id:
            print("  Discord notification skipped (not configured)")
            return False

        # Build embed
        if success:
            color = 0x00FF00  # Green
            title = "Deployment Successful"
            description = f"Version `{self.version}` deployed successfully"
        else:
            color = 0xFF0000  # Red
            title = "Deployment Failed"
            description = f"Version `{self.version}` deployment had errors"

        fields = [
            {"name": "Clusters", "value": ", ".join(clusters), "inline": True},
            {"name": "Components", "value": ", ".join(components), "inline": True},
        ]

        if errors:
            error_text = "\n".join(errors[:5])  # Limit to 5 errors
            if len(errors) > 5:
                error_text += f"\n... and {len(errors) - 5} more"
            fields.append({"name": "Errors", "value": f"```{error_text}```", "inline": False})

        embed = {
            "title": title,
            "description": description,
            "color": color,
            "fields": fields,
            "footer": {"text": "KTP Deploy"},
            "timestamp": datetime.datetime.utcnow().isoformat() + "Z",
        }

        payload = {
            "channel_id": channel_id,
            "secret": relay_secret,
            "embeds": [embed],
        }

        try:
            req = urllib.request.Request(
                relay_url,
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                if resp.status == 200:
                    print("  Discord notification sent")
                    return True
                else:
                    print(f"  Discord notification failed: HTTP {resp.status}")
                    return False
        except urllib.error.URLError as e:
            print(f"  Discord notification failed: {e}")
            return False
        except Exception as e:
            print(f"  Discord notification failed: {e}")
            return False

    def _connect(self, cluster: dict) -> paramiko.SSHClient:
        """Establish SSH connection to a cluster."""
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())

        # Support both password and key auth
        connect_kwargs = {
            "hostname": cluster["host"],
            "username": cluster["user"],
            "timeout": 30,
        }

        if cluster.get("password"):
            connect_kwargs["password"] = cluster["password"]
        else:
            # Use default SSH key
            connect_kwargs["look_for_keys"] = True

        ssh.connect(**connect_kwargs)
        return ssh

    def _get_server_dirs(self, cluster: dict) -> List[str]:
        """Get list of server directories for a cluster."""
        dirs = []
        for port in cluster["ports"]:
            dirs.append(f"dod-{port}")
        return dirs

    def _backup_file(self, sftp, remote_path: str, backup_dir: str) -> bool:
        """Create backup of a remote file before overwriting."""
        try:
            # Check if file exists
            try:
                sftp.stat(remote_path)
            except FileNotFoundError:
                return True  # Nothing to backup

            # Create backup directory
            try:
                sftp.mkdir(backup_dir)
            except OSError:
                pass  # Directory exists

            # Generate backup filename
            filename = os.path.basename(remote_path)
            timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_path = f"{backup_dir}/{filename}.{timestamp}.bak"

            # Copy to backup
            stdin, stdout, stderr = sftp.get_channel().transport.open_session().exec_command(
                f"cp {remote_path} {backup_path}"
            )
            return True
        except Exception as e:
            print(f"    Warning: Could not backup {remote_path}: {e}")
            return False

    def deploy_component(
        self,
        cluster_name: str,
        cluster: dict,
        component: str,
        dry_run: bool = False,
    ) -> bool:
        """Deploy a single component to a cluster."""
        if not cluster.get("host"):
            print(f"  Skipping {cluster_name}: No host configured")
            return False

        component_paths = self.config["paths"].get(component, [])
        if not component_paths:
            print(f"  No paths configured for component: {component}")
            return False

        print(f"  Deploying {component} to {cluster_name} ({cluster['host']})...")

        if dry_run:
            for path_config in component_paths:
                source = self.artifacts_dir / path_config["source"]
                print(f"    Would deploy: {source.name}")
            return True

        try:
            ssh = self._connect(cluster)
            sftp = ssh.open_sftp()

            server_dirs = self._get_server_dirs(cluster)
            success = True

            for server_dir in server_dirs:
                home_dir = f"/home/{cluster['user']}"
                backup_dir = f"{home_dir}/backups/{self.version}"

                for path_config in component_paths:
                    source = self.artifacts_dir / path_config["source"]
                    if not source.exists():
                        print(f"    Warning: Source not found: {source}")
                        continue

                    dest = f"{home_dir}/{server_dir}/{path_config['dest']}"

                    # Ensure destination directory exists
                    dest_dir = os.path.dirname(dest)
                    try:
                        sftp.stat(dest_dir)
                    except FileNotFoundError:
                        # Create directory hierarchy
                        self._mkdir_p(sftp, dest_dir)

                    # Backup existing file
                    self._backup_file_via_ssh(ssh, dest, backup_dir)

                    # Upload file
                    try:
                        sftp.put(str(source), dest)
                        print(f"    {server_dir}: {source.name} -> {path_config['dest']}")

                        # Set permissions if specified
                        if "chmod" in path_config:
                            sftp.chmod(dest, int(path_config["chmod"], 8))
                    except Exception as e:
                        print(f"    Error uploading {source.name} to {server_dir}: {e}")
                        success = False

            sftp.close()
            ssh.close()
            return success

        except Exception as e:
            print(f"  Error connecting to {cluster_name}: {e}")
            return False

    def _mkdir_p(self, sftp, remote_path: str):
        """Recursively create directory on remote."""
        dirs = []
        while remote_path:
            try:
                sftp.stat(remote_path)
                break
            except FileNotFoundError:
                dirs.append(remote_path)
                remote_path = os.path.dirname(remote_path)

        for d in reversed(dirs):
            try:
                sftp.mkdir(d)
            except OSError:
                pass

    def _backup_file_via_ssh(self, ssh, remote_path: str, backup_dir: str):
        """Create backup using SSH command."""
        try:
            # Check if file exists
            stdin, stdout, stderr = ssh.exec_command(f"test -f {remote_path} && echo exists")
            if stdout.read().decode().strip() != "exists":
                return

            # Create backup directory
            ssh.exec_command(f"mkdir -p {backup_dir}")

            # Copy to backup
            filename = os.path.basename(remote_path)
            timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_path = f"{backup_dir}/{filename}.{timestamp}.bak"
            ssh.exec_command(f"cp {remote_path} {backup_path}")
        except Exception:
            pass  # Backup is best-effort

    def configure_server_names(
        self,
        cluster_name: str,
        cluster: dict,
        dry_run: bool = False,
    ) -> bool:
        """Configure LinuxGSM server names for a cluster."""
        hostname = cluster.get("hostname", cluster_name)
        server_name_prefix = cluster.get("server_name_prefix", f"KTP {hostname.title()}")

        print(f"  Configuring server names for {cluster_name}...")
        print(f"    Hostname: {hostname}")
        print(f"    Server name prefix: {server_name_prefix}")

        if dry_run:
            for i, port in enumerate(cluster["ports"], 1):
                server_name = f"{server_name_prefix} #{i}"
                print(f"    Would set dod-{port}: {server_name}")
            return True

        try:
            ssh = self._connect(cluster)

            for i, port in enumerate(cluster["ports"], 1):
                server_name = f"{server_name_prefix} #{i}"
                exec_name = "dodserver" if i == 1 else f"dodserver{i}"
                home_dir = f"/home/{cluster['user']}"
                config_dir = f"{home_dir}/dod-{port}/lgsm/config-lgsm/dodserver"
                config_file = f"{config_dir}/{exec_name}.cfg"

                # Create config directory if needed
                ssh.exec_command(f"mkdir -p {config_dir}")

                # Check if config exists and update/create it
                stdin, stdout, stderr = ssh.exec_command(f"test -f {config_file} && echo exists")
                exists = stdout.read().decode().strip() == "exists"

                if exists:
                    # Update existing servername line or append it
                    ssh.exec_command(
                        f"grep -q '^servername=' {config_file} && "
                        f"sed -i 's/^servername=.*/servername=\"{server_name}\"/' {config_file} || "
                        f"echo 'servername=\"{server_name}\"' >> {config_file}"
                    )
                else:
                    # Create new config file
                    config_content = f'''# LinuxGSM Instance Configuration
# Instance {i} - Port {port}

port="{port}"
clientport="{port - 10}"
servername="{server_name}"

# Cluster: {hostname}
'''
                    ssh.exec_command(f"cat > {config_file} << 'EOFCFG'\n{config_content}\nEOFCFG")

                print(f"    dod-{port}: {server_name}")

            ssh.close()
            return True

        except Exception as e:
            print(f"  Error configuring server names for {cluster_name}: {e}")
            return False

    def deploy_configs(
        self,
        cluster_name: str,
        cluster: dict,
        profile: str,
        dry_run: bool = False,
    ) -> bool:
        """Deploy configuration files with profile-specific values."""
        if not self.template_env:
            print("  No templates directory found, skipping config deployment")
            return True

        profile_config = self.config["profiles"].get(profile, {})
        print(f"  Deploying configs to {cluster_name} with profile '{profile}'...")

        if dry_run:
            print(f"    Would apply profile: {profile_config}")
            return True

        try:
            ssh = self._connect(cluster)
            sftp = ssh.open_sftp()

            server_dirs = self._get_server_dirs(cluster)

            for server_dir in server_dirs:
                home_dir = f"/home/{cluster['user']}"
                config_dir = f"{home_dir}/{server_dir}/serverfiles/dod/addons/ktpamx/configs"

                # Ensure config directory exists
                self._mkdir_p(sftp, config_dir)

                # Render and deploy each template
                for template_name in self.template_env.list_templates():
                    if not template_name.endswith(".j2"):
                        continue

                    template = self.template_env.get_template(template_name)
                    rendered = template.render(
                        profile=profile_config,
                        cluster=cluster,
                        server_dir=server_dir,
                    )

                    # Remove .j2 extension for destination
                    dest_name = template_name[:-3]
                    dest_path = f"{config_dir}/{dest_name}"

                    # Write rendered config
                    with sftp.open(dest_path, "w") as f:
                        f.write(rendered)

                    print(f"    {server_dir}: {dest_name}")

            sftp.close()
            ssh.close()
            return True

        except Exception as e:
            print(f"  Error deploying configs to {cluster_name}: {e}")
            return False

    def deploy(
        self,
        clusters: List[str],
        components: List[str],
        profile: str = "online",
        dry_run: bool = False,
        deploy_configs: bool = False,
        configure_names: bool = False,
        notify_discord: bool = False,
    ) -> bool:
        """Deploy components to specified clusters."""
        print(f"KTP Deployment - Version {self.version}")
        print(f"Artifacts: {self.artifacts_dir}")
        print(f"Components: {', '.join(components)}")
        print(f"Clusters: {', '.join(clusters)}")
        print(f"Profile: {profile}")
        if configure_names:
            print("Server name configuration: ENABLED")
        if notify_discord:
            print("Discord notifications: ENABLED")
        if dry_run:
            print("DRY RUN - No changes will be made")
        print("")

        success = True
        errors = []

        for cluster_name in clusters:
            cluster = self.config["clusters"].get(cluster_name)
            if not cluster:
                print(f"Unknown cluster: {cluster_name}")
                errors.append(f"Unknown cluster: {cluster_name}")
                success = False
                continue

            print(f"\n{'='*50}")
            print(f"Cluster: {cluster_name}")
            if cluster.get("description"):
                print(f"  {cluster['description']}")
            print(f"{'='*50}")

            # Configure server names if requested
            if configure_names:
                if not self.configure_server_names(cluster_name, cluster, dry_run):
                    errors.append(f"{cluster_name}: Failed to configure server names")
                    success = False

            # Deploy components
            for component in components:
                if not self.deploy_component(cluster_name, cluster, component, dry_run):
                    errors.append(f"{cluster_name}: Failed to deploy {component}")
                    success = False

            # Deploy configs if requested
            if deploy_configs:
                if not self.deploy_configs(cluster_name, cluster, profile, dry_run):
                    errors.append(f"{cluster_name}: Failed to deploy configs")
                    success = False

        print(f"\n{'='*50}")
        if success:
            print("Deployment completed successfully!")
        else:
            print("Deployment completed with errors.")
        print(f"{'='*50}")

        # Send Discord notification
        if notify_discord and not dry_run:
            self.send_discord_notification(success, clusters, components, errors if not success else None)

        return success


def main():
    parser = argparse.ArgumentParser(
        description="Deploy KTP game server components",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s --cluster atlanta --version 20260127
  %(prog)s --all --component plugins --version 20260127
  %(prog)s --cluster denver --profile lan --version test
  %(prog)s --cluster atlanta --dry-run --version 20260127
        """,
    )

    # Target selection
    target_group = parser.add_mutually_exclusive_group(required=True)
    target_group.add_argument(
        "--cluster",
        help="Deploy to specific cluster (atlanta, dallas, denver)",
    )
    target_group.add_argument(
        "--all",
        action="store_true",
        help="Deploy to all production clusters",
    )

    # Component selection
    parser.add_argument(
        "--component",
        choices=["engine", "ktpamx", "plugins", "all"],
        default="all",
        help="Component to deploy (default: all)",
    )

    # Version
    parser.add_argument(
        "--version",
        required=True,
        help="Artifact version to deploy (e.g., 20260127)",
    )

    # Profile
    parser.add_argument(
        "--profile",
        choices=["online", "lan"],
        default="online",
        help="Configuration profile (default: online)",
    )

    # Options
    parser.add_argument(
        "--with-configs",
        action="store_true",
        help="Also deploy configuration files",
    )
    parser.add_argument(
        "--configure-names",
        action="store_true",
        help="Configure LinuxGSM server names (from config.yaml hostname/server_name_prefix)",
    )
    parser.add_argument(
        "--notify-discord",
        action="store_true",
        help="Send Discord notification on completion (requires relay config)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be deployed without making changes",
    )
    parser.add_argument(
        "--config",
        default=str(Path(__file__).parent / "config.yaml"),
        help="Path to config.yaml",
    )
    parser.add_argument(
        "--artifacts-dir",
        help="Override artifacts directory",
    )

    args = parser.parse_args()

    # Determine artifacts directory
    if args.artifacts_dir:
        artifacts_dir = Path(args.artifacts_dir)
    else:
        # Default: ../artifacts/{version}
        artifacts_dir = Path(__file__).parent.parent / "artifacts" / args.version

    if not artifacts_dir.exists():
        print(f"Error: Artifacts directory not found: {artifacts_dir}")
        print(f"Run 'make build VERSION={args.version}' first.")
        sys.exit(1)

    # Determine clusters
    if args.all:
        # All production clusters (exclude test clusters)
        deployer = KTPDeployer(args.config, str(artifacts_dir), args.version)
        clusters = [
            name
            for name, cfg in deployer.config["clusters"].items()
            if not cfg.get("test_cluster", False) and cfg.get("host")
        ]
    else:
        clusters = [args.cluster]

    # Determine components
    if args.component == "all":
        components = ["engine", "ktpamx", "plugins"]
    else:
        components = [args.component]

    # Deploy
    deployer = KTPDeployer(args.config, str(artifacts_dir), args.version)
    success = deployer.deploy(
        clusters=clusters,
        components=components,
        profile=args.profile,
        dry_run=args.dry_run,
        deploy_configs=args.with_configs,
        configure_names=args.configure_names,
        notify_discord=args.notify_discord,
    )

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
