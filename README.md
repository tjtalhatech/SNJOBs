# ServiceNow Leads Dashboard

A high-performance, responsive single-screen dashboard that shows fresh ServiceNow job leads from across the globe.

This application is designed to be **serverless and hosted on Vercel**, with data updated automatically twice a day via **GitHub Actions**. This setup is 100% free, requires no active server, and keeps all your API credentials completely secure.

---

## How It Works

```
[GitHub Actions (cron, 2x/day)]
     │
     ├── 1. Runs fetch_jobs.py (calls Adzuna + JSearch APIs)
     ├── 2. Merges & de-duplicates new leads
     ├── 3. Saves results to public/data/jobs.json
     └── 4. Commits & pushes public/data/jobs.json back to GitHub
             │
             └─── [GitHub Push Event]
                       │
                       └───► [Vercel Deployment]
                                 │
                                 └───► Rebuilds & serves updated static files to users!
```

---

## 🚀 Step-by-Step Deployment Guide

### Step 1: Create Your GitHub Repository
1. Go to [GitHub](https://github.com) and create a new **public** or **private** repository (e.g., `servicenow-leads`).
2. Push your project files from your local system or AI Studio export to your GitHub repository:
   ```bash
   git init
   git add .
   git commit -m "Initial setup"
   git branch -M main
   git remote add origin https://github.com/<your-username>/<your-repo-name>.git
   git push -u origin main
   ```

---

### Step 2: Manually Add the GitHub Actions Workflow
Because GitHub restricts external applications (like AI Studio) from pushing `.yml` workflow files to prevent unauthorized pipeline execution, you must add the workflow file manually:

1. In your GitHub repository webpage, click **Add file** ➔ **Create new file**.
2. Set the file path exactly as: `.github/workflows/fetch-jobs.yml`
3. Copy and paste the following YAML code into the file:

```yaml
name: Fetch ServiceNow Jobs

on:
  schedule:
    # Runs at 08:00 and 20:00 UTC daily (adjust as needed)
    - cron: '0 8 * * *'
    - cron: '0 20 * * *'
  workflow_dispatch: {} # Allows manual runs from the Actions tab

permissions:
  contents: write # Important: allows GitHub Actions to commit updated data

jobs:
  fetch-and-publish:
    runs-on: ubuntu-latest
    steps:
      - name: Checkout repo
        uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'

      - name: Fetch jobs
        env:
          ADZUNA_APP_ID: ${{ secrets.ADZUNA_APP_ID }}
          ADZUNA_APP_KEY: ${{ secrets.ADZUNA_APP_KEY }}
          ADZUNA_COUNTRIES: ${{ vars.ADZUNA_COUNTRIES }}
          RAPIDAPI_KEY: ${{ secrets.RAPIDAPI_KEY }}
          # JSearch JSearch has a small free quota — only call it on the 08:00 run.
          SKIP_JSEARCH: ${{ github.event.schedule == '0 20 * * *' && 'true' || 'false' }}
        run: python fetch_jobs.py

      - name: Commit updated data
        run: |
          git config user.name "github-actions[bot]"
          git config user.email "github-actions[bot]@users.noreply.github.com"
          git add public/data/jobs.json
          git diff --staged --quiet || git commit -m "Update job leads $(date -u +%Y-%m-%dT%H:%M:%SZ)"
          git push
```

4. Click **Commit changes** to save the file.

---

### Step 3: Configure API Keys in GitHub Secrets
To fetch jobs from Adzuna and JSearch, obtain keys (free) and save them securely on GitHub:

1. **Adzuna App Credentials** (Highly recommended, very generous free tier):
   - Register at [developer.adzuna.com](https://developer.adzuna.com/)
   - Create an app to get an `app_id` and `app_key`.
2. **JSearch Key via RapidAPI**:
   - Register at [RapidAPI JSearch](https://rapidapi.com/letscrape-6bRBa3QguO5/api/jsearch)
   - Subscribe to the free plan and copy the `X-RapidAPI-Key`.

#### Adding them to GitHub:
In your GitHub Repository, navigate to **Settings** ➔ **Secrets and variables** ➔ **Actions**:
- Click **New repository secret** and add:
  - `ADZUNA_APP_ID` ➔ (Your Adzuna App ID)
  - `ADZUNA_APP_KEY` ➔ (Your Adzuna App Key)
  - `RAPIDAPI_KEY` ➔ (Your RapidAPI Key)

*(Note: If you only have one of them, the python script will gracefully skip the other source.)*

---

### Step 4: Configure GitHub Action Permissions (CRITICAL)
For the workflow to successfully save the jobs data, you need to grant it write permissions:

1. Go to your GitHub Repository **Settings** ➔ **Actions** ➔ **General**.
2. Scroll down to **Workflow permissions**.
3. Select **Read and write permissions**.
4. Click **Save**.

---

### Step 5: Connect and Deploy to Vercel
1. Go to [Vercel](https://vercel.com) and log in.
2. Click **Add New** ➔ **Project** and import your GitHub repository.
3. Vercel will automatically detect the **Vite** framework:
   - **Framework Preset**: `Vite` (automatically detected)
   - **Build Command**: `vite build`
   - **Output Directory**: `dist`
4. Click **Deploy**!

#### 🔒 Why this setup is extremely secure:
Since Vercel only hosts your built static site, **you do not need to add any secrets/keys on Vercel!** Your API keys reside safely in GitHub Secrets and are only accessed during the GitHub Actions workflow run. The built client application simply fetches the raw static `public/data/jobs.json` file.

---

## Running the Workflow Manually
To seed your database/listings immediately without waiting for the scheduled times:
1. In your GitHub repository, click on the **Actions** tab.
2. Select **Fetch ServiceNow Jobs** from the left-hand sidebar.
3. Click the **Run workflow** dropdown on the right and click **Run workflow**.
4. Once it finishes, it will commit the new `public/data/jobs.json` file to your repo, which triggers Vercel to redeploy the fresh listings instantly!
