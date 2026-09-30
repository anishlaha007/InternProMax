# Run InternProMax on a free server

Set it up once and it stays on: listings keep syncing, your inbox keeps getting checked, and the dashboard works from your laptop or phone without starting anything.

**The plan:** a free cloud server runs InternProMax. [Tailscale](https://tailscale.com) (free for personal use) connects your laptop, phone and the server into a private network. The dashboard is never on the public internet, and it's password protected on top of that. The Chrome extension on your laptop talks to the server the same way.

```
 your laptop (Chrome + extension) ─┐
                                   ├── Tailscale private network ──► free server: InternProMax (always on)
 your phone (dashboard) ───────────┘
```

Time: about 30 minutes, most of it creating the cloud account.

---

## 1. Get a free server (pick one)

### Option A: Oracle Cloud "Always Free" (recommended)
The biggest free tier: an ARM server, up to 2 CPUs and 12 GB RAM, with a 200 GB disk. A card is required at sign-up for identity checks.

1. Sign up at <https://www.oracle.com/cloud/free/>.
2. Menu → **Compute → Instances → Create instance**.
   - **Image:** Canonical Ubuntu 24.04.
   - **Shape:** Ampere → `VM.Standard.A1.Flex`, 1 OCPU and 6 GB memory is plenty.
   - **SSH keys:** "Generate a key pair for me" and **download the private key**, or paste your own public key.
   - Create. If you get "Out of capacity", try another availability domain or try again later.
3. Copy the instance's **public IP**, then connect: `ssh -i path/to/key ubuntu@PUBLIC_IP`.

> Oracle can reclaim Always Free servers that sit nearly idle for a week. Upgrading the account to "Pay As You Go" stops that, and you still pay nothing while you stay inside the free limits. Set a budget alert of $1 to be safe.

### Option B: Google Cloud free e2-micro
1 GB RAM is enough for InternProMax. Must be in **us-west1, us-central1 or us-east1**.

1. <https://cloud.google.com/free> → create a project.
2. **Compute Engine → VM instances → Create**: region `us-central1`, machine `e2-micro`, boot disk Ubuntu 24.04 with a 30 GB **standard** persistent disk. Leave "External IP" as ephemeral (you won't need a static one; that costs money).
3. Use the **SSH** button in the console.

### Option C: a computer at home
Any always-on Mac, Linux box or Raspberry Pi 4/5. The script below is for Ubuntu/Debian. On other systems use Docker (section 6) or run `./run.sh` with the settings from section 6.

---

## 2. Install InternProMax on the server

On the server:

```bash
sudo apt-get update && sudo apt-get install -y git
git clone https://github.com/anishlaha007/InternProMax.git
cd InternProMax
sudo ./deploy/install.sh
```

> **Private repo?** GitHub will ask for a username and password. Use your GitHub username and a [personal access token](https://github.com/settings/tokens) (read-only "Contents" access to this repo) as the password.

The script:
1. installs Python and the app into `/opt/internpromax`, with your data in `/var/lib/internpromax`,
2. installs **Tailscale** and prints a login link: **open it and sign in** (use the same account you'll use on your laptop and phone),
3. asks you to **choose a password** for the dashboard and extension,
4. starts InternProMax as a background service that restarts on reboot, listening **only on the Tailscale network**,
5. prints the address to use, normally **`http://internpromax:8420`**.

---

## 3. Connect your devices

1. Install Tailscale on your **laptop** and **phone** (<https://tailscale.com/download>) and sign in with the **same account**.
2. Open **`http://internpromax:8420/`** (type the `http://` part in full) and log in with your password.
3. **Profile → Load profile file** to load your profile JSON, then **Upload PDF** your resume.
4. The first listings sync starts on its own. Check **Settings → Job lists**.

### Chrome extension
1. On your laptop, get the repo (`git clone …` or download the ZIP) and load `extension/` at `chrome://extensions` (Developer mode → Load unpacked).
2. Right-click the extension icon → **Options**.
3. Server address: `http://internpromax:8420`. Password: yours. Click **Connect**.
4. Chrome asks to let the extension access that address: click **Allow**. You should see **"Connected and logged in ✓"**.

After that everything works as before: Apply from the dashboard or open any application page, and it autofills, attaches the tailored resume, and tracks the submission.

---

## 4. Day-to-day

| Task | How |
|---|---|
| See logs | `journalctl -u internpromax -f` |
| Restart | `sudo systemctl restart internpromax` |
| Update to the latest code | `cd ~/InternProMax && git pull && sudo ./deploy/install.sh` (keeps your data and password) |
| Change the password | `sudo IPM_PASSWORD='new password' ./deploy/install.sh`, then reconnect the extension in Options |
| Back up | `sudo tar czf internpromax-backup.tgz -C /var/lib internpromax` and copy it off the server (`scp`) |
| Restore | stop the service, untar into `/var/lib`, `sudo chown -R internpromax: /var/lib/internpromax`, start it |
| Settings file | `/etc/internpromax.env` (address, port, allowed host names). The password is in `/etc/internpromax.password`. |

### Optional: HTTPS on your tailnet
Traffic inside Tailscale is already encrypted. If you still want an `https://` address:
```bash
sudo tailscale serve --bg http://$(tailscale ip -4):8420
```
Then use the `https://internpromax.<your-tailnet>.ts.net` address it prints, in the browser and in the extension's Options.

---

## 5. Is it safe?

- Nothing is exposed to the public internet. The app only listens on the server's Tailscale address, and cloud firewalls stay closed.
- Everything requires your password. Wrong guesses are rate-limited, and login cookies are HttpOnly.
- Requests from other websites are rejected, and only the host names in `IPM_ALLOWED_HOSTS` are answered.
- The service runs as its own locked-down user and can only write to `/var/lib/internpromax`.
- Your Anthropic API key and email app password (if you add them) are stored in the server's database, inside that folder.

---

## 6. Other ways to run it

### Docker (any OS, including a home server)
```bash
cp .env.example .env      # set IPM_PASSWORD, IPM_ALLOWED_HOSTS, IPM_PUBLISH
docker compose up -d
```
Set `IPM_PUBLISH` to the machine's Tailscale IP (`tailscale ip -4`) so port 8420 is only reachable over Tailscale. Data is kept in `./data`.

### Without Tailscale (your own domain)
Only if you know what you're doing: run `sudo IPM_NO_TAILSCALE=1 IPM_ALLOWED_HOSTS=jobs.yourdomain.com ./deploy/install.sh` and put an HTTPS reverse proxy (for example Caddy: `jobs.yourdomain.com { reverse_proxy 127.0.0.1:8420 }`) in front. The password is then the only thing between the internet and your data. Use a long one.

### Manually
```bash
IPM_PASSWORD='your password' IPM_ALLOWED_HOSTS=internpromax,100.x.y.z \
  python -m internpromax serve --host 100.x.y.z --no-browser
```
InternProMax refuses to listen on anything other than localhost unless a password is set.

---

## Troubleshooting

| Problem | Fix |
|---|---|
| `http://internpromax:8420` doesn't load | Is Tailscale connected on this device? Try the `100.x.y.z` address the script printed. On the server: `systemctl status internpromax`. |
| "This host name isn't allowed" | Add the name you're using to `IPM_ALLOWED_HOSTS` in `/etc/internpromax.env`, then `sudo systemctl restart internpromax`. |
| Extension says "Log in" | Options → Connect again (the password may have changed). |
| Extension says "Offline" | Check the server address in Options and that Tailscale is on. |
| Oracle "Out of capacity" | Try a different availability domain, a smaller shape, or again later. |
