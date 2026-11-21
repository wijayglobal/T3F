# Deploying with GitHub Actions

Pushes to `main` are tested and then deployed to the server. The setup follows course_portal: GitHub
SSHes in as a restricted `deploy` user whose key can only run `deploy/ci.sh`.

```
push to main ─▶ Test and deploy: tests on Postgres + docker build
                     │ (only if green)
                     ▼
               ssh deploy@server "deploy <sha>"  ──forced command──▶  sudo deploy/ci.sh
                                                                         └─ deploy/deploy.sh: git pull --ff-only,
                                                                            docker compose up -d --build, wait for the site
```

| Workflow | When | What |
|---|---|---|
| `Test and deploy` (`.github/workflows/deploy.yml`) | every push / PR | `check`, missing-migration check, tests on Postgres 16, `docker build`; on `main` it then deploys |
| `Server tasks` (`.github/workflows/server-tasks.yml`) | by hand (Actions → Run workflow) | `status`, `deploy`, `restart`, `backup`, `build-embeddings` |
| `Scheduled backup` (`.github/workflows/backup.yml`) | daily 03:30 IST | `deploy/backup.sh`: `pg_dump` to `backups/`, 14 days kept |

The scheduled backup replaces the cron line in the README. Use one or the other.

## One-time server setup

1. Install Docker with the compose plugin, then clone and configure:

   ```bash
   sudo git clone https://github.com/godisai-in/kalaisol.git /opt/kalaichol
   sudo cp /opt/kalaichol/.env.example /opt/kalaichol/.env
   sudo nano /opt/kalaichol/.env      # DJANGO_SECRET_KEY, POSTGRES_PASSWORD, ALLOWED_HOSTS, SITE_URL, SMTP, WEB_PORT
   ss -tlnp                           # WEB_PORT (default 8081) must be free
   ```

2. Create the deploy user and the CI key:

   ```bash
   sudo sh /opt/kalaichol/deploy/setup_server.sh kalaichol.example.com
   ```

   It prints the four secrets below. Add them at GitHub: **repo → Settings → Environments → `production`**
   (or as plain repository secrets):

   | Secret | Value |
   |---|---|
   | `DEPLOY_SSH_HOST` | the server's host name or IP |
   | `DEPLOY_SSH_USER` | `deploy` |
   | `DEPLOY_SSH_KEY` | the private key it prints (`/root/github-keys/kalaichol_deploy`) |
   | `DEPLOY_KNOWN_HOSTS` | the host-key lines it prints |

   An environment also lets you require a manual approval before each deploy (Environments → production →
   Required reviewers).

3. First start, then the data and an admin:

   ```bash
   sudo /opt/kalaichol/deploy/ci.sh deploy
   cd /opt/kalaichol
   sudo docker compose exec web python manage.py createsuperuser
   sudo docker compose exec web python manage.py import_wiktionary data_raw/tamil.jsonl
   sudo docker compose exec web python manage.py build_embeddings
   ```

   The image only has what the website needs (about 420 MB). `import_wiktionary` and `build_embeddings`
   work in it. `import_english`, `machine_draft`, `export_dataset` and `push_hf` need the data tools: run them
   on a machine with `uv sync`, or build a full image with `--build-arg UV_GROUPS=--all-groups`.

   `data_raw/` isn't in git (it's large). Copy what you need to `/opt/kalaichol/data_raw/` with `rsync`
   first; it's mounted into the container.

4. HTTPS: add `deploy/Caddyfile` (or its nginx version) to the server's proxy.

## Private repo

If the repo is private, the server pulls with a read-only deploy key:

```bash
sudo mkdir -p /root/github-keys
sudo ssh-keygen -t ed25519 -N '' -C kalaichol-pull -f /root/github-keys/github_pull
sudo cat /root/github-keys/github_pull.pub   # GitHub: repo → Settings → Deploy keys → Add (no write access)
sudo git -C /opt/kalaichol remote set-url origin git@github.com:godisai-in/kalaisol.git
```

`deploy/deploy.sh` picks the key up automatically.

## By hand

Every task runs on the server too, and each one is logged to `/var/log/kalaichol_ci.log`:

```bash
sudo /opt/kalaichol/deploy/ci.sh status
sudo /opt/kalaichol/deploy/ci.sh backup
```

Restore a backup:

```bash
gunzip -c backups/kalaichol-YYYY-MM-DD.sql.gz | sudo docker compose exec -T db psql -U kalaichol -d kalaichol
```
