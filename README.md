# Family wishlist: deployment (Ubuntu/Debian VPS)

```bash
# 1. Copy the project and create a service user
sudo adduser --system --group --home /opt/wishlist wishlist
sudo cp -r wishlist/* /opt/wishlist/ && sudo chown -R wishlist:wishlist /opt/wishlist

# 2. Install dependencies
sudo apt install python3-venv
sudo -u wishlist python3 -m venv /opt/wishlist/venv
sudo -u wishlist /opt/wishlist/venv/bin/pip install -r /opt/wishlist/requirements.txt

# 3. Set your password (stored as a hash in data/password_hash.txt)
cd /opt/wishlist && sudo -u wishlist venv/bin/python set_password.py

# 4. Edit deploy/wishlist.service (secret login path, title), then:
sudo cp deploy/wishlist.service /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable --now wishlist

# 5. Add deploy/nginx-wishlist.conf into your HTTPS server block
sudo nginx -t && sudo systemctl reload nginx
```

Your login page is `https://your-domain/<WISHLIST_ADMIN_PATH>/`.
Make sure nginx's user (www-data) can read `/opt/wishlist/uploads` and `/opt/wishlist/static`
(e.g. `sudo chmod o+rx /opt/wishlist`).
Back up `data/` and `uploads/` to keep your wishes.
Change the welcome text in `app.py` (or via `WISHLIST_WELCOME` in the service file).

