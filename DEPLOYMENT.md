# Google Cloud Deployment Guide

This guide covers deploying the PDF Tools Flask application to Google Cloud Platform.

## Option 1: Google App Engine (Recommended - Easiest)

### Prerequisites
1. Install [Google Cloud SDK](https://cloud.google.com/sdk/docs/install)
2. Create a Google Cloud Project at [console.cloud.google.com](https://console.cloud.google.com)
3. Enable billing for your project

### Steps

1. **Authenticate with Google Cloud:**
   ```bash
   gcloud auth login
   ```

2. **Set your project:**
   ```bash
   gcloud config set project YOUR_PROJECT_ID
   ```

3. **Enable App Engine API:**
   ```bash
   gcloud app create --region=us-central
   ```
   (Choose a region close to your users)

4. **Deploy the application:**
   ```bash
   gcloud app deploy
   ```

5. **View your application:**
   ```bash
   gcloud app browse
   ```

Your app will be available at: `https://YOUR_PROJECT_ID.appspot.com`

### Configuration

The `app.yaml` file configures:
- **Runtime:** Python 3.13
- **Instance class:** F2 (1GB RAM, suitable for PDF processing)
- **Auto-scaling:** 0-10 instances based on traffic
- **Static files:** Automatically served from `/static` directory

### Costs

- App Engine has a free tier (28 hours/day of F1 instances)
- F2 instances cost approximately $0.05/hour
- First 1GB of storage and 5GB of outgoing traffic are free monthly

---

## Option 2: Google Cloud Run (Serverless Containers)

### Prerequisites
1. Install [Google Cloud SDK](https://cloud.google.com/sdk/docs/install)
2. Create a Google Cloud Project
3. Enable billing

### Steps

1. **Authenticate and set project:**
   ```bash
   gcloud auth login
   gcloud config set project YOUR_PROJECT_ID
   ```

2. **Enable Cloud Run API:**
   ```bash
   gcloud services enable run.googleapis.com
   ```

3. **Build and deploy:**
   ```bash
   # Build the container
   gcloud builds submit --tag gcr.io/YOUR_PROJECT_ID/pdf-tools
   
   # Deploy to Cloud Run
   gcloud run deploy pdf-tools \
     --image gcr.io/YOUR_PROJECT_ID/pdf-tools \
     --platform managed \
     --region us-central1 \
     --allow-unauthenticated \
     --memory 1Gi \
     --timeout 300 \
     --max-instances 10
   ```

4. **Get your URL:**
   ```bash
   gcloud run services describe pdf-tools --platform managed --region us-central1
   ```

### Configuration

The `Dockerfile` uses:
- **Base image:** Python 3.13 slim
- **Server:** Gunicorn (production WSGI server)
- **Port:** Uses PORT environment variable (Cloud Run sets this automatically)

### Costs

- Cloud Run charges only for actual usage (per request)
- First 2 million requests per month are free
- Memory and CPU time are billed per second

---

## Updating the Application

### App Engine
```bash
gcloud app deploy
```

### Cloud Run
```bash
gcloud builds submit --tag gcr.io/YOUR_PROJECT_ID/pdf-tools
gcloud run deploy pdf-tools --image gcr.io/YOUR_PROJECT_ID/pdf-tools --platform managed --region us-central1
```

---

## Environment Variables (Optional)

If you need to set environment variables:

### App Engine
Add to `app.yaml`:
```yaml
env_variables:
  YOUR_VAR: 'value'
```

### Cloud Run
```bash
gcloud run deploy pdf-tools \
  --update-env-vars YOUR_VAR=value \
  --platform managed \
  --region us-central1
```

---

## Troubleshooting

### View logs:
```bash
# App Engine
gcloud app logs tail -s default

# Cloud Run
gcloud run services logs read pdf-tools --platform managed --region us-central1
```

### Check deployment status:
```bash
# App Engine
gcloud app versions list

# Cloud Run
gcloud run services describe pdf-tools --platform managed --region us-central1
```

---

## Recommended: App Engine

For this Flask application, **App Engine is recommended** because:
- ✅ No Dockerfile needed
- ✅ Automatic HTTPS
- ✅ Built-in load balancing
- ✅ Easy deployment with `gcloud app deploy`
- ✅ Free tier available
- ✅ Auto-scaling handled automatically

