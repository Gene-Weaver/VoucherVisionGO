#!/bin/bash
# Script to deploy the VoucherVision API to Google Cloud Run

# Set your Google Cloud project ID
PROJECT_ID="your-project-id"

# Set the name for your Cloud Run service
SERVICE_NAME="vouchervision-api"

# Set the region
REGION="us-central1"

# Build and push the container image to Google Container Registry
echo "Building and pushing container image..."
gcloud builds submit --tag gcr.io/$PROJECT_ID/$SERVICE_NAME

# Deploy the container image to Cloud Run
echo "Deploying to Cloud Run..."
gcloud run deploy $SERVICE_NAME \
  --image gcr.io/$PROJECT_ID/$SERVICE_NAME \
  --platform managed \
  --region $REGION \
  --allow-unauthenticated \
  --memory 2Gi \
  --cpu 2 \
  --timeout 300s \
  --set-env-vars API_KEY=$API_KEY

echo "Deployment complete!"
echo "Your API is now available at:"
gcloud run services describe $SERVICE_NAME --platform managed --region $REGION --format 'value(status.url)'