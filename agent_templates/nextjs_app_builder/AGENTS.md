# App Builder Instructions

You are a Prototyping Engineer. Your goal is to build a full-stack Next.js dashboard from scratch.

## Execution Workflow
1. **Setup Auth:** Run `bash /skills/git_auth/setup.sh` to configure git authentication.
2. **Initialize Project:** Create a local directory `/workspace/local-temp/dashboard` and initialize the project there.
   Run this exact command: `mkdir -p /workspace/local-temp/dashboard && cd /workspace/local-temp/dashboard && npx -y create-next-app@latest . --ts --tailwind --eslint --app --src-dir --import-alias "@/*" --yes --disable-git --skip-install`.
3. **Data Mocking:** Create a local mock data file `src/data/marketing_campaigns.json` containing realistic dummy data for marketing campaigns.
4. **Dashboard UI:** Overwrite `src/app/page.tsx`. Build a data table displaying the raw marketing data.
5. **Git Push:** Initialize git manually from that directory (`git init && git config user.name 'Agent' && git config user.email 'agent@test.com' && git add . && git commit -m 'init'`), and push it to `https://github.com/ayushiagarwal11-eng/agent-dashboard-test.git` using `git push --force`.
6. **Sync Output:** Run `rsync -a --exclude node_modules --exclude .git /workspace/local-temp/dashboard/ /workspace/output/dashboard/` to persist the code.
