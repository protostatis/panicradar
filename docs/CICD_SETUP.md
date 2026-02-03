# CI/CD Setup Guide

This project uses GitHub Actions for continuous integration and deployment.

## Workflows

### CI (`ci.yml`)
Runs on every push and PR to `main` and `product-development` branches.

**Jobs:**
1. **Test Backend** - Lints and tests Python code with uv
2. **Test Frontend** - Lints and builds React app
3. **Build Docker** - Validates Docker images build successfully

### Deploy (`deploy.yml`)
Runs when a new release is published.

**Jobs:**
1. **Build and Push** - Builds Docker images and pushes to GitHub Container Registry
2. **Deploy** - SSHs to EC2 and deploys the new images

## Required Secrets

Configure these in GitHub repo settings: **Settings → Secrets and variables → Actions**

| Secret | Description | Example |
|--------|-------------|---------|
| `EC2_HOST` | EC2 public IP or hostname | `34.229.95.72` |
| `EC2_USERNAME` | SSH username | `ec2-user` |
| `EC2_SSH_KEY` | Private SSH key (full content) | Contents of `~/.ssh/crypto-sentiment-key.pem` |

**Note:** `GITHUB_TOKEN` is automatically provided by GitHub Actions.

## Setting Up Secrets

### 1. Get your SSH private key
```bash
cat ~/.ssh/crypto-sentiment-key.pem
```

### 2. Add secrets in GitHub
1. Go to your repo on GitHub
2. Click **Settings** → **Secrets and variables** → **Actions**
3. Click **New repository secret**
4. Add each secret:
   - Name: `EC2_HOST`, Value: `34.229.95.72`
   - Name: `EC2_USERNAME`, Value: `ec2-user`
   - Name: `EC2_SSH_KEY`, Value: (paste entire key including BEGIN/END lines)

## Creating a Release

### Via GitHub UI
1. Go to **Releases** → **Create a new release**
2. Click **Choose a tag** → type version (e.g., `v1.0.0`) → **Create new tag**
3. Fill in release title and notes
4. Click **Publish release**

### Via CLI
```bash
# Create and push a tag
git tag -a v1.0.0 -m "Release v1.0.0"
git push origin v1.0.0

# Create release via gh CLI
gh release create v1.0.0 --title "v1.0.0" --notes "Release notes here"
```

## Deployment Flow

```
1. Developer creates release tag (v1.x.x)
           ↓
2. GitHub Actions triggers deploy.yml
           ↓
3. Build Docker images (crawler, api, frontend)
           ↓
4. Push to GitHub Container Registry (ghcr.io)
           ↓
5. SSH to EC2
           ↓
6. Pull new images from ghcr.io
           ↓
7. Restart containers with new images
           ↓
8. Deployment complete!
```

## Environment Protection (Optional)

For additional safety, you can require approval before deploying:

1. Go to **Settings** → **Environments**
2. Create environment named `production`
3. Enable **Required reviewers**
4. Add yourself or team members as reviewers

## Troubleshooting

### Deployment fails with SSH error
- Verify `EC2_SSH_KEY` contains the full private key
- Check EC2 security group allows SSH from GitHub Actions IPs
- Verify the key has correct permissions on EC2

### Docker build fails
- Check Dockerfile syntax
- Verify all required files are committed
- Check build logs for specific errors

### Container won't start
- Check `docker logs <container-name>` on EC2
- Verify environment variables are set
- Check network configuration

## Local Testing

Test the CI workflow locally using [act](https://github.com/nektos/act):

```bash
# Install act
brew install act

# Run CI workflow
act push

# Run specific job
act push -j test-backend
```
