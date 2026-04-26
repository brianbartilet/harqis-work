# OpenClaw Environment Integration Guide

This guide shows how to integrate the OpenClaw environment setup with various development tools, CI/CD systems, and workflows.

## Table of Contents

1. [Development Tools](#development-tools)
2. [CI/CD Pipelines](#cicd-pipelines)
3. [Containerization](#containerization)
4. [IDE Configuration](#ide-configuration)
5. [Shell & Terminal](#shell--terminal)
6. [Cloud Platforms](#cloud-platforms)

---

## Development Tools

### JetBrains IDEs (PyCharm, IntelliJ, WebStorm)

#### Option 1: Edit Run Configuration XML

Edit `.run/openclaw-tui.run.xml` to include environment variables:

```xml
<component name="ProjectRunConfigurationManager">
  <configuration default="false" name="openclaw-tui" type="ShConfigurationType">
    <option name="SCRIPT_TEXT" value="openclaw tui" />
    <option name="SCRIPT_PATH" value="" />
    <option name="SCRIPT_OPTIONS" value="" />
    <option name="SCRIPT_WORKING_DIRECTORY" value="$PROJECT_DIR$" />
    <option name="INTERPRETER_PATH" value="/bin/bash" />
    <option name="EXECUTE_IN_TERMINAL" value="true" />
    
    <!-- Add environment variables -->
    <envs>
      <env name="OPENCLAW_CONFIG_PATH" value="$PROJECT_DIR$/.openclaw/config" />
      <env name="OPENCLAW_STATE_DIR" value="$PROJECT_DIR$/.openclaw/state" />
    </envs>
    
    <method v="2" />
  </configuration>
</component>
```

#### Option 2: Via GUI

1. **Run** → **Edit Configurations**
2. Select your OpenClaw run configuration
3. Click **Modify Options** → **Environment variables**
4. Add:
   ```
   OPENCLAW_CONFIG_PATH=./.openclaw/config
   OPENCLAW_STATE_DIR=./.openclaw/state
   ```

### VS Code

#### Add to Workspace Settings

Create or edit `.vscode/settings.json`:

```json
{
  "terminal.integrated.env.windows": {
    "OPENCLAW_CONFIG_PATH": "${workspaceFolder}/.openclaw/config",
    "OPENCLAW_STATE_DIR": "${workspaceFolder}/.openclaw/state"
  },
  "terminal.integrated.env.osx": {
    "OPENCLAW_CONFIG_PATH": "${workspaceFolder}/.openclaw/config",
    "OPENCLAW_STATE_DIR": "${workspaceFolder}/.openclaw/state"
  },
  "terminal.integrated.env.linux": {
    "OPENCLAW_CONFIG_PATH": "${workspaceFolder}/.openclaw/config",
    "OPENCLAW_STATE_DIR": "${workspaceFolder}/.openclaw/state"
  }
}
```

#### Add Task Configuration

Add to `.vscode/tasks.json`:

```json
{
  "version": "2.0.0",
  "tasks": [
    {
      "label": "Setup OpenClaw Environment",
      "type": "shell",
      "command": "${workspaceFolder}/.openclaw/setup-env.sh",
      "problemMatcher": [],
      "presentation": {
        "reveal": "always",
        "panel": "new"
      }
    },
    {
      "label": "OpenClaw TUI",
      "type": "shell",
      "command": "openclaw tui",
      "dependsOn": ["Setup OpenClaw Environment"],
      "problemMatcher": []
    }
  ]
}
```

### Visual Studio

Add to `.vs/ProjectName/config/applicationhost.config`:

```xml
<system.webServer>
  <httpProtocol>
    <customHeaders>
      <add name="OPENCLAW_CONFIG_PATH" value=".\.openclaw\config" />
      <add name="OPENCLAW_STATE_DIR" value=".\.openclaw\state" />
    </customHeaders>
  </httpProtocol>
</system.webServer>
```

---

## CI/CD Pipelines

### GitHub Actions

Create `.github/workflows/openclaw-setup.yml`:

```yaml
name: Setup OpenClaw Environment

on: [push, pull_request, workflow_dispatch]

jobs:
  setup:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      
      - name: Set up OpenClaw environment
        run: |
          chmod +x .openclaw/setup-env.sh
          ./.openclaw/setup-env.sh "${{ github.workspace }}/.openclaw/workspace"
      
      - name: Verify setup
        run: |
          echo "OPENCLAW_CONFIG_PATH=$OPENCLAW_CONFIG_PATH"
          echo "OPENCLAW_STATE_DIR=$OPENCLAW_STATE_DIR"
          ls -la "$OPENCLAW_CONFIG_PATH"
          ls -la "$OPENCLAW_STATE_DIR"
```

### GitLab CI

Add to `.gitlab-ci.yml`:

```yaml
variables:
  OPENCLAW_CONFIG_PATH: "$CI_PROJECT_DIR/.openclaw/config"
  OPENCLAW_STATE_DIR: "$CI_PROJECT_DIR/.openclaw/state"

setup_openclaw:
  stage: setup
  script:
    - mkdir -p "$OPENCLAW_CONFIG_PATH" "$OPENCLAW_STATE_DIR"
    - echo "OpenClaw environment configured"
    - ls -la "$OPENCLAW_CONFIG_PATH"
  artifacts:
    paths:
      - .openclaw/config/
    expire_in: 1 week
```

### Jenkins

Add to `Jenkinsfile`:

```groovy
pipeline {
    agent any
    
    environment {
        OPENCLAW_CONFIG_PATH = "${WORKSPACE}/.openclaw/config"
        OPENCLAW_STATE_DIR = "${WORKSPACE}/.openclaw/state"
    }
    
    stages {
        stage('Setup OpenClaw') {
            steps {
                sh 'mkdir -p $OPENCLAW_CONFIG_PATH $OPENCLAW_STATE_DIR'
                sh 'echo "Config Path: $OPENCLAW_CONFIG_PATH"'
                sh 'echo "State Path: $OPENCLAW_STATE_DIR"'
            }
        }
        
        stage('Run OpenClaw') {
            steps {
                sh 'openclaw status'
            }
        }
    }
}
```

### Azure Pipelines

Add to `azure-pipelines.yml`:

```yaml
variables:
  OPENCLAW_CONFIG_PATH: $(Build.SourcesDirectory)/.openclaw/config
  OPENCLAW_STATE_DIR: $(Build.SourcesDirectory)/.openclaw/state

stages:
  - stage: Setup
    jobs:
      - job: ConfigureOpenClaw
        pool:
          vmImage: 'ubuntu-latest'
        steps:
          - task: Bash@3
            inputs:
              targetType: 'inline'
              script: |
                mkdir -p "$OPENCLAW_CONFIG_PATH" "$OPENCLAW_STATE_DIR"
                echo "OPENCLAW_CONFIG_PATH=$OPENCLAW_CONFIG_PATH" >> $(Build.BuildNumber).env
```

---

## Containerization

### Docker

Create a Dockerfile with OpenClaw setup:

```dockerfile
FROM node:20-alpine

WORKDIR /app

# Copy repository
COPY . .

# Install OpenClaw
RUN npm install -g openclaw

# Setup environment
ENV OPENCLAW_CONFIG_PATH=/app/.openclaw/config
ENV OPENCLAW_STATE_DIR=/app/.openclaw/state

# Create directories
RUN mkdir -p $OPENCLAW_CONFIG_PATH $OPENCLAW_STATE_DIR

# Make setup script executable
RUN chmod +x .openclaw/setup-env.sh

# Default command
CMD ["openclaw", "tui"]
```

Use with Docker Compose:

```yaml
version: '3.8'

services:
  openclaw:
    build: .
    environment:
      OPENCLAW_CONFIG_PATH: /app/.openclaw/config
      OPENCLAW_STATE_DIR: /app/.openclaw/state
    volumes:
      - ./.openclaw/config:/app/.openclaw/config
      - ./.openclaw/state:/app/.openclaw/state
    ports:
      - "9001:9001"
    stdin_open: true
    tty: true
```

### Kubernetes

Create `openclaw-deployment.yaml`:

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: openclaw-env
data:
  OPENCLAW_CONFIG_PATH: "/data/openclaw/config"
  OPENCLAW_STATE_DIR: "/data/openclaw/state"

---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: openclaw
spec:
  replicas: 1
  selector:
    matchLabels:
      app: openclaw
  template:
    metadata:
      labels:
        app: openclaw
    spec:
      containers:
      - name: openclaw
        image: openclaw:latest
        envFrom:
        - configMapRef:
            name: openclaw-env
        volumeMounts:
        - name: openclaw-config
          mountPath: /data/openclaw/config
        - name: openclaw-state
          mountPath: /data/openclaw/state
      volumes:
      - name: openclaw-config
        persistentVolumeClaim:
          claimName: openclaw-config-pvc
      - name: openclaw-state
        persistentVolumeClaim:
          claimName: openclaw-state-pvc
```

---

## IDE Configuration

### Cursor

Add to `.cursor/settings.json`:

```json
{
  "terminal.integrated.env.windows": {
    "OPENCLAW_CONFIG_PATH": "${workspaceFolder}/.openclaw/config",
    "OPENCLAW_STATE_DIR": "${workspaceFolder}/.openclaw/state"
  }
}
```

### Nova (Panic)

Create `.nova/tasks.json`:

```json
{
  "version": "2.0",
  "tasks": [
    {
      "label": "OpenClaw Setup",
      "shell": true,
      "command": "./.openclaw/setup-env.sh",
      "capture": true,
      "notify": true
    }
  ]
}
```

---

## Shell & Terminal

### Bash

Add to `~/.bashrc`:

```bash
# OpenClaw environment
if [[ -d "$HOME/GIT/harqis-work/.openclaw" ]]; then
    export OPENCLAW_CONFIG_PATH="$HOME/GIT/harqis-work/.openclaw/config"
    export OPENCLAW_STATE_DIR="$HOME/GIT/harqis-work/.openclaw/state"
fi
```

### Zsh

Add to `~/.zshrc`:

```zsh
# OpenClaw environment
if [[ -d "$HOME/GIT/harqis-work/.openclaw" ]]; then
    export OPENCLAW_CONFIG_PATH="$HOME/GIT/harqis-work/.openclaw/config"
    export OPENCLAW_STATE_DIR="$HOME/GIT/harqis-work/.openclaw/state"
fi
```

### Fish

Add to `~/.config/fish/config.fish`:

```fish
# OpenClaw environment
if test -d ~/GIT/harqis-work/.openclaw
    set -gx OPENCLAW_CONFIG_PATH ~/GIT/harqis-work/.openclaw/config
    set -gx OPENCLAW_STATE_DIR ~/GIT/harqis-work/.openclaw/state
end
```

### PowerShell

Add to `$PROFILE`:

```powershell
# OpenClaw environment
$openclawRoot = "C:\Users\$env:USERNAME\GIT\harqis-work\.openclaw"
if (Test-Path $openclawRoot) {
    $env:OPENCLAW_CONFIG_PATH = "$openclawRoot\config"
    $env:OPENCLAW_STATE_DIR = "$openclawRoot\state"
}
```

---

## Cloud Platforms

### AWS Lambda

Set environment variables in CloudFormation:

```yaml
OpenClawFunction:
  Type: AWS::Lambda::Function
  Properties:
    Environment:
      Variables:
        OPENCLAW_CONFIG_PATH: /mnt/data/.openclaw/config
        OPENCLAW_STATE_DIR: /mnt/data/.openclaw/state
    Layers:
      - arn:aws:lambda:region:account:layer:openclaw
```

### Google Cloud Functions

Set in `cloudfunctions.yaml`:

```yaml
apiVersion: cloudfunctions.googleapis.com/v1
kind: CloudFunction
metadata:
  name: openclaw-function
spec:
  environmentVariables:
    - name: OPENCLAW_CONFIG_PATH
      value: /workspace/.openclaw/config
    - name: OPENCLAW_STATE_DIR
      value: /workspace/.openclaw/state
```

### Azure Functions

Set in `local.settings.json`:

```json
{
  "IsEncrypted": false,
  "Values": {
    "AzureWebJobsStorage": "",
    "FUNCTIONS_WORKER_RUNTIME": "node",
    "OPENCLAW_CONFIG_PATH": "./.openclaw/config",
    "OPENCLAW_STATE_DIR": "./.openclaw/state"
  }
}
```

### Heroku

Set config vars:

```bash
heroku config:set OPENCLAW_CONFIG_PATH=/app/.openclaw/config
heroku config:set OPENCLAW_STATE_DIR=/app/.openclaw/state
```

Or in `Procfile`:

```
web: OPENCLAW_CONFIG_PATH=/app/.openclaw/config OPENCLAW_STATE_DIR=/app/.openclaw/state openclaw tui
```

---

## Makefile Integration

Use the provided Makefile for quick setup:

```bash
# Setup with make
make setup

# Verify
make verify

# Custom profile
make setup PROFILE=work

# Clean
make clean
```

---

## Automation Scripts

### Bash Automation

Create a `scripts/setup-all.sh`:

```bash
#!/bin/bash
set -e

echo "Setting up OpenClaw environment..."

# Make setup scripts executable
chmod +x .openclaw/setup-env.sh
chmod +x .openclaw/setup-env.ps1

# Run platform-specific setup
if [[ "$OSTYPE" == "msys" ]] || [[ "$OSTYPE" == "cygwin" ]]; then
    powershell -NoProfile -ExecutionPolicy Bypass -File ".openclaw/setup-env.ps1"
else
    ./.openclaw/setup-env.sh
fi

echo "Setup complete!"
openclaw status
```

### Python Automation

Create a `scripts/setup_openclaw.py`:

```python
#!/usr/bin/env python3
import os
import sys
from pathlib import Path

def setup_openclaw(sync_repo=None, profile="default", permanent=False):
    """Setup OpenClaw environment variables."""
    
    if sync_repo is None:
        sync_repo = Path.cwd() / ".openclaw" / "workspace"
    else:
        sync_repo = Path(sync_repo)
    
    if not sync_repo.exists():
        print(f"Error: Sync repository not found: {sync_repo}")
        sys.exit(1)
    
    config_path = sync_repo / "config"
    state_path = sync_repo / "state"
    
    # Create directories
    config_path.mkdir(parents=True, exist_ok=True)
    state_path.mkdir(parents=True, exist_ok=True)
    
    # Set environment variables
    os.environ["OPENCLAW_CONFIG_PATH"] = str(config_path)
    os.environ["OPENCLAW_STATE_DIR"] = str(state_path)
    
    if profile != "default":
        os.environ["OPENCLAW_PROFILE"] = profile
    
    print(f"✓ OPENCLAW_CONFIG_PATH={config_path}")
    print(f"✓ OPENCLAW_STATE_DIR={state_path}")
    
    if permanent:
        # Save to ~/.openclaw.env
        env_file = Path.home() / ".openclaw.env"
        with open(env_file, "w") as f:
            f.write(f"export OPENCLAW_CONFIG_PATH={config_path}\n")
            f.write(f"export OPENCLAW_STATE_DIR={state_path}\n")
            if profile != "default":
                f.write(f"export OPENCLAW_PROFILE={profile}\n")
        print(f"✓ Saved to {env_file}")

if __name__ == "__main__":
    setup_openclaw(permanent=False)
```

---

## Troubleshooting Integration

### Check Current Configuration

```bash
# Verify environment variables are set
echo $OPENCLAW_CONFIG_PATH
echo $OPENCLAW_STATE_DIR

# Check OpenClaw is using the right paths
openclaw health

# List active configuration
openclaw config get agents.defaults.workspace
```

### Debug Environment Setup

```bash
# Create a debug script
cat > .openclaw/debug-env.sh << 'EOF'
#!/bin/bash
echo "=== OpenClaw Environment Debug ==="
echo "OPENCLAW_CONFIG_PATH=${OPENCLAW_CONFIG_PATH:-NOT SET}"
echo "OPENCLAW_STATE_DIR=${OPENCLAW_STATE_DIR:-NOT SET}"
echo "OPENCLAW_PROFILE=${OPENCLAW_PROFILE:-default}"
echo ""
echo "Directory contents:"
ls -la "$OPENCLAW_CONFIG_PATH" 2>/dev/null || echo "Config directory not found"
ls -la "$OPENCLAW_STATE_DIR" 2>/dev/null || echo "State directory not found"
EOF

chmod +x .openclaw/debug-env.sh
./.openclaw/debug-env.sh
```

---

## Best Practices

1. **Always source setup scripts** before running OpenClaw
2. **Commit setup scripts** to version control but exclude sensitive config
3. **Use profiles** for different environments (dev, prod, personal)
4. **Verify after setup** with `openclaw status`
5. **Document custom setup** in your project's README
6. **Use .gitignore** to exclude state and sensitive config
7. **Test on multiple platforms** if your team uses different OSs

---

**Last Updated:** 2026-04-26  
**Tested On:** OpenClaw 2026.4.2
