#!/bin/bash
set -e

# Configuration
AWS_REGION="ap-northeast-1"
REPO_NAME="realtime-sip-bot"
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
ECR_URI="${ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com/${REPO_NAME}"

echo ">>> Building and pushing Docker image to ECR: ${ECR_URI}"

# Login to ECR
echo ">>> Logging in to ECR..."
aws ecr get-login-password --region ${AWS_REGION} | docker login --username AWS --password-stdin ${ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com

# Build Docker image for linux/amd64 and push directly
# Using --push ensures the multi-platform/cross-compiled build is uploaded directly
echo ">>> Building and Pushing Docker image (platform: linux/amd64)..."
docker buildx build --platform linux/amd64 -t ${ECR_URI}:latest --push .

echo ">>> Successfully pushed ${ECR_URI}:latest"
