# accounts/

One directory per GHL account (or whitelabel) you administer. **Everything here except this
README and `default.example` is git-ignored** — it holds live credentials.

```
accounts/
├── default                 # one line: the name of the account to use when -a is omitted
└── <name>/
    ├── refresh_token.txt   # long-lived Firebase refresh token (chmod 600) — full account access
    └── token.txt           # short-lived idToken, auto-rotated by ghl.sh (chmod 600)
```

Setup (see the repo `README.md` for how to capture the refresh token from your browser):

```bash
mkdir -p accounts/main
echo 'AMf-...' > accounts/main/refresh_token.txt
chmod 600 accounts/main/refresh_token.txt
cp accounts/default.example accounts/default   # or: echo 'main' > accounts/default
```

Target a specific account on any command with `-a <name>`. A `refresh_token.txt` is the
equivalent of a long-lived password — never commit it, paste it, or share it.
