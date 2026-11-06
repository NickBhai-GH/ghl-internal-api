# accounts/

Credentials for the GHL accounts (or whitelabels) you administer. **Everything here except this
README and `default.example` is git-ignored**: it holds live credentials.

```
accounts/
├── vault.kdbx              # KeePassXC vault: entry title = account name, password = refresh token
├── lock_minutes            # optional: minutes before the toolkit locks again (default 60, 0 = until reboot)
├── default                 # one line: the name of the account to use when -a is omitted
└── <name>/
    └── token.txt           # short-lived idToken, auto-rotated by ghl.sh (chmod 600)
```

Setup (see the repo `README.md` for how to capture the refresh token from your browser):

```bash
wl-paste | ./ghl.sh vault-add main             # token on the clipboard; first run creates the vault
cp accounts/default.example accounts/default   # or: echo 'main' > accounts/default
echo 60 > accounts/lock_minutes                # optional: ask for the vault password every 60 min
```

Target a specific account on any command with `-a <name>`. A refresh token is the equivalent
of a long-lived password: it lives only in the vault and in RAM while unlocked. Never write it
to a file, commit it, paste it, or share it.
