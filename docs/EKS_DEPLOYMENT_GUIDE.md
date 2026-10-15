# Complete End-to-End AWS EKS Deployment Guide
## IT-Ops Multi-Agent Incident Summariser

This document provides a production-grade, step-by-step operational guide to deploy the **IT-Ops Multi-Agent Incident Summariser** onto **Amazon Elastic Kubernetes Service (AWS EKS)** with **Amazon Aurora PostgreSQL (pgvector)**, **Amazon ECR**, and **AWS Application Load Balancer (ALB)**.

---

## 1. High-Level Production Architecture

```mermaid
flowchart TD
    subgraph ClientLayer [External Traffic]
        User[DevOps / SRE Engineer Browser] --> Route53[Amazon Route 53 DNS]
        Route53 --> ACM[AWS Certificate Manager SSL/TLS]
        Route53 --> ALB[AWS Application Load Balancer]
    end

    subgraph AWSVPC [AWS Virtual Private Cloud (VPC)]
        subgraph PublicSubnets [Public Subnets (Multi-AZ)]
            ALB
            NAT[NAT Gateways]
        end

        subgraph PrivateSubnets [Private App Subnets (EKS Managed Nodes)]
            ALB --> Ingress[Kubernetes Ingress (AWS ALB Controller)]
            Ingress --> Service[ClusterIP Service: port 80]
            Service --> Pod1[Pod: itops-incident-summariser (AZ-a)]
            Service --> Pod2[Pod: itops-incident-summariser (AZ-b)]
            HPA[Horizontal Pod Autoscaler] -. Scales .-> Pod1
        end

        subgraph DatabaseSubnets [Isolated Database Subnets]
            Pod1 --> Aurora[(Amazon Aurora PostgreSQL 16 + pgvector)]
            Pod2 --> Aurora
        end
    end

    subgraph ExternalSaaS [Third-Party Services]
        Pod1 --> Gemini[Google Gemini LLM & Embeddings API]
        Pod2 --> Gemini
        Pod1 --> GitHub[GitHub REST API / Webhooks]
        Pod2 --> GitHub
        Pod1 --> Langfuse[Langfuse Observability Cloud]
        Pod2 --> Langfuse
    end
```

---

## 2. Prerequisites & Local Tooling

Ensure the following CLI tools are installed and configured on your management machine:
- **AWS CLI v2**: `aws --version` (authenticated with Administrator or EKS-provisioning IAM role)
- **eksctl**: `eksctl version` (v0.170.0+)
- **kubectl**: `kubectl version --client` (v1.28+)
- **Docker**: `docker --version`
- **Helm v3**: `helm version`

```bash
# Verify AWS credentials
aws sts get-caller-identity
```

Export your standard deployment environment variables:
```bash
export AWS_REGION="us-east-1"
export AWS_ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
export CLUSTER_NAME="itops-production-eks"
export ECR_REPO_NAME="itops-incident-summariser"
export IMAGE_TAG="v0.1.0"
```

---

## 3. Step-by-Step Deployment Procedure

### Step 1: Create Amazon ECR Repository & Build Container Image

1. **Create the ECR repository**:
   ```bash
   aws ecr create-repository \
     --repository-name ${ECR_REPO_NAME} \
     --region ${AWS_REGION} \
     --image-scanning-configuration scanOnPush=true \
     --encryption-configuration encryptionType=AES256
   ```

2. **Authenticate Docker with Amazon ECR**:
   ```bash
   aws ecr get-login-password --region ${AWS_REGION} | \
     docker login --username AWS --password-stdin ${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com
   ```

3. **Build the production Docker image**:
   ```bash
   # Execute from repository root
   docker build \
     -t ${ECR_REPO_NAME}:${IMAGE_TAG} \
     -f docker/Dockerfile .
   ```

4. **Tag and push to ECR**:
   ```bash
   export ECR_IMAGE_URI="${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com/${ECR_REPO_NAME}:${IMAGE_TAG}"

   docker tag ${ECR_REPO_NAME}:${IMAGE_TAG} ${ECR_IMAGE_URI}
   docker push ${ECR_IMAGE_URI}
   ```

---

### Step 2: Provision AWS EKS Cluster with `eksctl`

Create a dedicated production cluster across 3 availability zones with managed node groups in private subnets:

```bash
cat <<EOF > eks-cluster-config.yaml
apiVersion: eksctl.io/v1alpha5
kind: ClusterConfig

metadata:
  name: ${CLUSTER_NAME}
  region: ${AWS_REGION}
  version: "1.30"

iam:
  withOIDC: true # Required for IAM Roles for Service Accounts (IRSA)

vpc:
  cidr: "10.100.0.0/16"
  nat:
    gateway: HighlyAvailable # 1 NAT Gateway per AZ

managedNodeGroups:
  - name: general-workers
    instanceType: m6i.large
    minSize: 2
    maxSize: 6
    desiredCapacity: 2
    privateNetworking: true
    volumeSize: 50
    volumeType: gp3
    labels:
      workload: general
    iam:
      withAddonPolicies:
        autoScaler: true
        albIngress: true
        cloudWatch: true

cloudWatch:
  clusterLogging:
    enableTypes: ["api", "audit", "authenticator", "controllerManager", "scheduler"]
EOF

# Create cluster (takes ~15-20 minutes)
eksctl create cluster -f eks-cluster-config.yaml

# Verify cluster connectivity
kubectl get nodes
```

---

### Step 3: Provision PostgreSQL with `pgvector` on AWS RDS / Aurora

1. **Create DB Security Group**:
   ```bash
   # Retrieve EKS Node Security Group ID
   NODE_SG=$(aws eks describe-cluster --name ${CLUSTER_NAME} --query "cluster.resourcesVpcConfig.clusterSecurityGroupId" --output text)

   # Create DB Security Group
   DB_SG=$(aws ec2 create-security-group \
     --group-name itops-aurora-pgvector-sg \
     --description "Security group for Aurora PostgreSQL with pgvector" \
     --vpc-id $(aws eks describe-cluster --name ${CLUSTER_NAME} --query "cluster.resourcesVpcConfig.vpcId" --output text) \
     --query "GroupId" --output text)

   # Allow inbound port 5432 from EKS worker nodes
   aws ec2 authorize-security-group-ingress \
     --group-id ${DB_SG} \
     --protocol tcp \
     --port 5432 \
     --source-group ${NODE_SG}
   ```

2. **Create RDS Subnet Group & PostgreSQL 16 Instance**:
   Create an Amazon RDS PostgreSQL 16 instance (or Aurora Serverless v2 PostgreSQL 16) in your private subnets. Ensure parameter group has `shared_preload_libraries = 'vector'`.

3. **Initialize the `pgvector` extension**:
   Connect to the database via a bastion host or port-forward pod:
   ```sql
   -- Connect as postgres admin
   CREATE DATABASE itops_incident_db;
   \c itops_incident_db
   CREATE EXTENSION IF NOT EXISTS vector;
   -- Verify extension is installed
   SELECT extname, extversion FROM pg_extension WHERE extname = 'vector';
   ```

---

### Step 4: Install AWS Load Balancer Controller

The AWS Load Balancer Controller manages AWS ALBs for Kubernetes Ingress resources.

1. **Associate IAM OIDC Provider**:
   ```bash
   eksctl utils associate-iam-oidc-provider --cluster ${CLUSTER_NAME} --approve
   ```

2. **Download and create IAM Policy**:
   ```bash
   curl -o iam_policy.json https://raw.githubusercontent.com/kubernetes-sigs/aws-load-balancer-controller/main/docs/install/iam_policy.json

   aws iam create-policy \
     --policy-name AWSLoadBalancerControllerIAMPolicy \
     --policy-document file://iam_policy.json
   ```

3. **Create ServiceAccount with IRSA**:
   ```bash
   eksctl create iamserviceaccount \
     --cluster=${CLUSTER_NAME} \
     --namespace=kube-system \
     --name=aws-load-balancer-controller \
     --attach-policy-arn=arn:aws:iam::${AWS_ACCOUNT_ID}:policy/AWSLoadBalancerControllerIAMPolicy \
     --override-existing-serviceaccounts \
     --approve
   ```

4. **Install AWS Load Balancer Controller using Helm**:
   ```bash
   helm repo add eks https://aws.github.io/eks-charts
   helm repo update

   helm install aws-load-balancer-controller eks/aws-load-balancer-controller \
     -n kube-system \
     --set clusterName=${CLUSTER_NAME} \
     --set serviceAccount.create=false \
     --set serviceAccount.name=aws-load-balancer-controller
   ```

---

### Step 5: Configure Kubernetes Namespace, ConfigMap & Secrets

1. **Apply Namespace**:
   ```bash
   kubectl apply -f k8s/namespace.yaml
   ```

2. **Apply ConfigMap**:
   ```bash
   kubectl apply -f k8s/configmap.yaml
   ```

3. **Create Secrets**:
   Edit `k8s/secret.example.yaml` or generate directly via CLI:
   ```bash
   kubectl create secret generic itops-secrets \
     --namespace=itops-incident-summariser \
     --from-literal=DATABASE_URL="postgresql+psycopg://dbuser:StrongPassword123@your-aurora-endpoint.rds.amazonaws.com:5432/itops_incident_db" \
     --from-literal=GEMINI_API_KEY="AIzaSy_YOUR_ACTUAL_GEMINI_KEY" \
     --from-literal=GITHUB_TOKEN="ghp_OPTIONAL_GITHUB_TOKEN" \
     --from-literal=LANGFUSE_PUBLIC_KEY="pk-lf-placeholder" \
     --from-literal=LANGFUSE_SECRET_KEY="sk-lf-placeholder"
   ```

---

### Step 6: Run Database Migrations on EKS (Kubernetes Job)

Execute Alembic migrations to create tables and vector indexes inside the Aurora PostgreSQL cluster:

1. **Update image URI in `k8s/migration-job.yaml`**:
   Replace `123456789012.dkr.ecr.us-east-1.amazonaws.com/...` with your `${ECR_IMAGE_URI}`.

2. **Run migration job**:
   ```bash
   kubectl apply -f k8s/migration-job.yaml
   ```

3. **Check migration status**:
   ```bash
   kubectl wait --for=condition=complete --timeout=120s job/itops-db-migration -n itops-incident-summariser
   kubectl logs job/itops-db-migration -n itops-incident-summariser
   ```

---

### Step 7: Deploy Application, Service, HPA & ALB Ingress

1. **Update `k8s/deployment.yaml` with your ECR image URI**:
   Ensure `image: <your-account-id>.dkr.ecr.<region>.amazonaws.com/itops-incident-summariser:v0.1.0`.

2. **Deploy Application & Service**:
   ```bash
   kubectl apply -f k8s/deployment.yaml
   kubectl apply -f k8s/service.yaml
   kubectl apply -f k8s/hpa.yaml
   ```

3. **Configure and Apply Ingress**:
   In `k8s/ingress.yaml`:
   - Replace `arn:aws:acm:...` with your valid ACM SSL Certificate ARN.
   - Replace `itops-summariser.internal.enterprise.com` with your Route 53 hostname.

   ```bash
   kubectl apply -f k8s/ingress.yaml
   ```

4. **Verify Application Rollout**:
   ```bash
   kubectl rollout status deployment/itops-incident-summariser -n itops-incident-summariser
   kubectl get pods -n itops-incident-summariser -o wide
   ```

---

### Step 8: Verify Endpoint Health & Ingress

1. **Retrieve ALB DNS Name**:
   ```bash
   kubectl get ingress itops-incident-summariser -n itops-incident-summariser
   ```

2. **Test Health Endpoint**:
   ```bash
   ALB_HOST=$(kubectl get ingress itops-incident-summariser -n itops-incident-summariser -o jsonpath='{.status.loadBalancer.ingress[0].hostname}')
   
   curl -I http://${ALB_HOST}/health
   # Expected: HTTP/1.1 200 OK
   ```

3. **Access Dashboard**:
   Open `https://${ALB_HOST}` in your browser to interact with the command center dashboard.

---

## 4. Operational Monitoring & Day-2 Playbook

### Checking Application Logs
```bash
kubectl logs -n itops-incident-summariser -l app.kubernetes.io/name=itops-incident-summariser --tail=100 -f
```

### Performing Zero-Downtime Rolling Update
```bash
# Push new image tag
docker build -t ${ECR_REPO_NAME}:v0.1.1 -f docker/Dockerfile .
docker tag ${ECR_REPO_NAME}:v0.1.1 ${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com/${ECR_REPO_NAME}:v0.1.1
docker push ${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com/${ECR_REPO_NAME}:v0.1.1

# Update Deployment
kubectl set image deployment/itops-incident-summariser \
  app=${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com/${ECR_REPO_NAME}:v0.1.1 \
  -n itops-incident-summariser

kubectl rollout status deployment/itops-incident-summariser -n itops-incident-summariser
```

### Rollback if Needed
```bash
kubectl rollout undo deployment/itops-incident-summariser -n itops-incident-summariser
```

---

## 5. Teardown / Cleanup

To delete all provisioned AWS resources and avoid unnecessary cloud charges:
```bash
# 1. Delete Kubernetes Ingress (removes AWS ALB)
kubectl delete -f k8s/ingress.yaml

# 2. Delete Namespace resources
kubectl delete namespace itops-incident-summariser

# 3. Delete EKS Cluster and Node Groups
eksctl delete cluster --name ${CLUSTER_NAME} --region ${AWS_REGION}

# 4. Delete ECR Repository
aws ecr delete-repository --repository-name ${ECR_REPO_NAME} --force --region ${AWS_REGION}
```
