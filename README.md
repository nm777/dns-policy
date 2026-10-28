# dns-policy

Per-device DNS policy for this Ubuntu home-network server. A Python CLI manages
fixed Kea DHCP reservations and routes selected IPv4 clients through a separate
dnsdist upstream pool. Devices are **protected by default**; bypasses can be timed
or permanent.

## Layout

- `dns-policy`: standard-library Python CLI, including its offline self-check.
- `setup`: idempotent runtime initialization, Kea read ACLs, and CLI installation.
- `compose.yml`: pinned dnsdist 2.1 container, host networking, restricted capabilities.
- `config/dnsdist.conf`: versioned starting configuration; copied once during setup.
- `examples/kea-dhcp4.conf`: minimal Kea shape required by the CLI; review before use.
- `test-setup.py`: offline initialization/adoption regression check.
- `dns-policy-integration-check`: optional **site-specific, disruptive** live check.
- `staging/dnsdist/`: ignored runtime directory (or link to an existing deployment).
  Contains `dnsdist.conf`, `console.key`, `policy.state`, and `.policy.lock`.
- `.env`: ignored Compose UID/GID settings, generated for the setup user.

Console keys, live policy state, DHCP leases, and real device reservations are not
tracked. The repository retains the current site's addresses and local DNS names
in the configuration template.

## Current network assumptions

| Setting | Default |
| --- | --- |
| dnsdist listener / DHCP-advertised DNS | `192.168.0.91:53` |
| DNS client ACL | `192.168.0.0/24` |
| Host address / local DNS answers | `192.168.0.111` |
| Encrypted local console | `127.0.0.1:5199` |
| Compose project / container | `dns-policy-staging` / `dns-policy-staging-dnsdist-1` |
| Kea config | `/etc/kea/kea-dhcp4.conf` |
| Kea lease journal | `/var/lib/kea/kea-leases4.csv` (plus cleanup journals) |
| Kea control socket | `/run/kea/kea4-ctrl-socket` |
| Kea service | `kea-dhcp4-server.service` |

Protected queries use OpenDNS over TLS (`208.67.222.222`, `208.67.220.220`);
configure the site's filtering policy with that provider. Bypass queries use
Cloudflare Families over TLS (`1.1.1.3`, `1.0.0.3`), which still filters malware
and adult content. A bypass therefore means bypassing the OpenDNS policy, not
unfiltered DNS. Certificates are verified; DNSSEC validation is delegated to the
providers. The pools have separate caches, and expired grants stop routing to the
bypass pool immediately without requiring a cleanup job.

## Prerequisites

Linux host networking, Python 3.9+, Docker Engine with the Compose v2 plugin,
working Docker access for your normal user, and an already configured Kea DHCPv4
server. On Ubuntu the non-Docker packages are:

```bash
sudo apt install python3 acl kea-dhcp4-server dnsutils
docker compose version
docker info
```

Install Docker Engine and the Compose plugin using Docker's Ubuntu installation
instructions if needed: <https://docs.docker.com/engine/install/ubuntu/>.

The host must already own `.91` and `.111`, with TCP/UDP 53 on `.91` available.
Allow LAN DNS traffic to `.91` and outbound TCP 853 to the upstream providers.
DHCP must advertise `.91`; existing clients may need to renew their leases.
Setup manages neither host addresses nor firewall/router/DHCP configuration.

For a different network, edit the address/ACL/local-record settings in
`staging/dnsdist/dnsdist.conf` after setup, configure Kea accordingly, and update
the CLI's `.91` usage/success messages. Its Kea paths and container name are
constants near the top of `dns-policy`. The live integration check is specific
to the network above.

## New deployment

Run setup **as your normal user**, from this directory:

```bash
./setup
# Review staging/dnsdist/dnsdist.conf and configure host addresses and Kea.
./setup --start
dns-policy list
```

Setup generates a random console key and an empty, protected-only policy, records
your UID/GID for the container, installs `~/.local/bin/dns-policy` as a symlink,
and grants your account read-only access to Kea data using sudo. Add
`~/.local/bin` to PATH if it is not already present. Existing runtime files are
preserved on reruns. `--start` validates the dnsdist configuration before starting
or recreating the container; Docker pulls the pinned image if missing.

Kea needs a UNIX control socket, a persisted memfile lease database, subnet IDs,
and a `reservations` array in each managed subnet. The CLI expects strict JSON
(no comments or trailing commas), even though Kea itself accepts extensions.
Use `examples/kea-dhcp4.conf` as a structural reference, not as a replacement for
an existing network configuration. The reservation installer currently requires
the live config to be `root:root` mode `0644` and the exact control-socket object
shown in the example. Validate Kea changes with `sudo kea-dhcp4 -t FILE` before
applying them through your normal deployment process.

## Adopt this machine's existing deployment

```bash
./setup --adopt /home/nate/Documents/docker/unbound/staging/dnsdist --skip-permissions
dns-policy list
dns-policy list --protected
```

This links the repo runtime directory to the existing data and redirects the CLI
symlink to this checkout. It preserves the console key, policy entries, saved
generation, and running container. `--skip-permissions` is appropriate here
because the Kea ACL repair has already been applied. Omit it when ACLs need repair.

To move container lifecycle management to this checkout later, use
`./setup --start`. The Compose project/service names intentionally match the
existing deployment; this recreates the same dnsdist service with this repo's
entrypoint and UID/GID settings. It briefly interrupts DNS service. Manage it from
this checkout afterward rather than alternating between the old and new Compose
files. The new entrypoint launches dnsdist directly and uses its protected-only
behavior on invalid policy state, without depending on the old image startup
wrapper or static fallback config.

## Commands

```bash
dns-policy list
dns-policy list --protected
dns-policy reserve                       # interactive: reserve an active lease
dns-policy bypass                        # interactive: type, device, duration
dns-policy bypass DEVICE                 # interactive: duration in minutes
dns-policy bypass DEVICE --for 30m        # s, m, h, d
dns-policy bypass DEVICE --permanent
dns-policy protect                       # interactive: remove an active bypass
dns-policy protect DEVICE
```

`DEVICE` is a unique fixed reservation's hostname or IPv4 address. Unreserved
leases cannot receive bypasses: reserve them first so an IP-only grant cannot
transfer to another device. Private/randomized MACs require confirmation that
they are stable. Interactive commands require a terminal on stdin and stdout.
Only clients actually using `.91` are affected; this does not enforce DNS use
against clients choosing other resolvers or encrypted DNS.

Normal commands must run **without sudo**. `reserve` requests sudo only for its
internal installer, which locks, validates, backs up, atomically installs, reloads,
and verifies Kea changes, with rollback on failure.

## Checks

```bash
./dns-policy --self-check
python3 test-setup.py
docker compose config --quiet
dns-policy list
dns-policy list --protected
dig @192.168.0.91 example.com
```

The offline checks do not change the network or policy. Both list commands must
report saved/live generations **in sync** and exit zero.

`./dns-policy-integration-check` is retained from the deployed system. It requires
exactly the ten original permanent bypasses, the `living-room` reservation at
`.110`, and the original addresses. It changes grants, stops/starts/restarts
dnsdist, verifies routing and rollback, and restores the seeded policy on cleanup.
Run it only during a maintenance window on this site; it is not a generic install
smoke test.

## Permissions and recovery

Recent Ubuntu Kea packaging restricts `/etc/kea` and `/var/lib/kea` to `_kea`.
`./setup` grants only directory traversal/config read access plus lease-directory
read access and default ACLs so newly rotated journals remain readable. It does
not grant your account write access to Kea configuration or leases. Rerun it after
a package upgrade if permissions are reset.

`staging/dnsdist` must be owned by the setup user with mode `0700`; its files use
`0600`. The container drops to that user's UID/GID. If an earlier sudo invocation
left root-owned state, repair just that file (using the actual runtime path):

```bash
sudo chown "$(id -u):$(id -g)" staging/dnsdist/policy.state
dns-policy list
```

State updates are locked, atomically replaced, fsynced, and verified against the
live generation. On apply failure the CLI attempts durable and live rollback.
If it reports `UNRECONCILED`, restore dnsdist availability, reapply the intended
policy operation, and require `dns-policy list` to pass. Do not delete state to
resolve a permissions problem. Invalid startup state selects protected-only
routing; if the protected upstreams are unavailable, queries fail rather than
fall through to bypass upstreams.

Back up the resolved runtime directory securely, especially `policy.state`,
`console.key`, and the deployed `dnsdist.conf`, plus `/etc/kea/kea-dhcp4.conf`.
The installer writes timestamped Kea backups beside the live configuration.
Treat console keys and host backups as secrets. A Git clone alone restores code
and default configuration, not the live grants or device inventory.
