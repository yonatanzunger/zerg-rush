# **Agent Control Panel (“Zerg Rush”)**

This is an app to securely deploy and manage fleets of agents created using tools like openclaw. The app is intended to run in a cloud environment (e.g. App Engine), limiting access to authorized users, and to allow you to:

* Spin up agents, each running in their own VM with only the credentials you have given them, and with a dedicated channel (e.g. a cloud storage directory) for exchanging data with them;  
* Monitor the status of agents;  
* Converse with those agents (e.g. by linking to their communication channels);  
* Turn agent states into “templates” that can then be copied, and roll back the state of an agent to a previous state;  
* Delete agents that are no longer used.

The most important principle of this application is that **agents must be isolated: compromise of a single agent must not compromise any other resources.** This is because agents are highly vulnerable to security failures that leak everything, including all of their credentials.

The app stores its own state in a combination of a database and a keyvault. It has a concept of users, which are authenticated using OAuth (so e.g. you use a Google account to sign in), and all data is segmented by user ID. For each user, it stores:

* Information about each active agent:  
  * A pointer to its VM and its data exchange channels  
  * Information about the image with which it was created (which binary, which version, which template)  
  * Key metadata, such as the agent’s name and its current task  
  * Which credentials the agent has access to  
* This user’s saved agents; a saved agent has a name (by default, the agent name plus the timestamp of the save) and includes  
  * Which script to use to set up the VM (e.g., the script to set up a clean openclaw instance)  
  * Additional config files to copy in after it is set up (e.g., after an openclaw instance “hatches,” we can snapshot its various configuration files)  
  * Whether this saved agent is “starred.” Starred saved agents are meant to be used as templates to create other agents.  
* Credentials that may be given to agents (stored in the keyvault), such as:  
  * LLM credentials (needed by all agents)  
  * Root cloud credentials (used by the app to create limited credentials for just the data exchange directories)  
  * Utility services like search engines or code repositories that can be granted to an agent

The app includes the following pages:

* The main landing page, from which you can create an account or log in.  
* The main logged-in landing page, from which you see all your current and starred saved agents, and can create new agents;  
* The detail page for an active agent, which allows you to converse with it, act on it, and examine its state;  
* The detail page for a saved agent, which allows you to examine and edit its state, star and unstar it, and delete it;  
* The page from which you can explore all saved agents, and take bulk actions like deleting many of them.  
* The page from which you can view a log of all actions you have taken within the app.

The basic ways to create an agent are:

* Create a basic agent – just install and set up the appropriate binaries on the VM.  
  * For example, you create an openclaw agent by creating a new VM; installing nodejs and pnpm on it using apt; installing openclaw on it by pulling the openclaw image and running the installation script; giving it its base credentials (LLM, communication paths like WhatsApp or Discord bot tokens); and then starting the binary. At this point, the user should have a first “hatching” conversation with it, after which they may want to save its state as a template.  
* Create an agent from a template – just like creating a basic agent, but before starting the binary, also copying in additional files or installing additional credentials, as per the template.

The basic actions you can take on an active agent are:

* Archive the agent: Snapshot its current state to create a new saved agent.  
* Pause the agent: Kill all the running jobs on the VM, but leave the VM ready to restart.  
* Delete the agent: Destroy the VM and all its state.  
* Recreate the agent from a snapshot: Delete the agent and replace it with a fresh agent from a snapshot.  
* Examine the agent: Browse, view, and edit the state of all files on the VM.  
* SSH in to the agent VM  
* Talk to the agent: Directly converse with it.

The basic actions you can take on a stored agent are:

* Copy the stored agent  
* Star or unstar the stored agent  
* Examine the stored agent: Exactly as for an active agent  
* Create an agent using it as a template.

The app must also write a log of all actions taken on it. Each user must be able to view their own log, and the log must be append-only; you cannot edit or delete log lines.

## Cloud Account Requirements

All cloud operations (creating agents, managing storage, accessing secrets) are performed using **your own cloud credentials**, obtained during OAuth login. This ensures:
- You maintain full control over resources created in your cloud account
- You can audit all actions in your cloud provider's logs
- No shared application credentials can be compromised

### GCP Users

When you log in with your Google account, the app requests permission to manage cloud resources on your behalf. You need the following IAM roles in your GCP project:

| Role | Purpose |
|------|---------|
| `roles/compute.admin` | Create and manage agent VMs |
| `roles/run.admin` | Create and manage Cloud Run services (if using Cloud Run) |
| `roles/storage.admin` | Create storage buckets for agent data exchange |
| `roles/secretmanager.admin` | Store and retrieve credentials for agents |
| `roles/iam.serviceAccountUser` | Attach service accounts to VMs/containers |

**To grant these roles:**
```bash
PROJECT_ID=your-project-id
USER_EMAIL=your-email@gmail.com

gcloud projects add-iam-policy-binding $PROJECT_ID \
  --member="user:$USER_EMAIL" \
  --role="roles/compute.admin"

gcloud projects add-iam-policy-binding $PROJECT_ID \
  --member="user:$USER_EMAIL" \
  --role="roles/run.admin"

gcloud projects add-iam-policy-binding $PROJECT_ID \
  --member="user:$USER_EMAIL" \
  --role="roles/storage.admin"

gcloud projects add-iam-policy-binding $PROJECT_ID \
  --member="user:$USER_EMAIL" \
  --role="roles/secretmanager.admin"

gcloud projects add-iam-policy-binding $PROJECT_ID \
  --member="user:$USER_EMAIL" \
  --role="roles/iam.serviceAccountUser"
```

### Azure Users

When you log in with your Microsoft account, the app requests permission to manage Azure resources. You need the following RBAC roles:

| Role | Scope | Purpose |
|------|-------|---------|
| `Contributor` | Resource Group | Create and manage ACI containers, storage, Key Vault |
| `Key Vault Secrets Officer` | Key Vault | Store and retrieve credentials for agents |
| `Storage Blob Data Contributor` | Storage Account | Manage agent data exchange blobs |

**To grant these roles:**
```bash
SUBSCRIPTION_ID=your-subscription-id
RESOURCE_GROUP=zerg-rush-rg
USER_OBJECT_ID=$(az ad user show --id your-email@domain.com --query id -o tsv)

az role assignment create \
  --assignee $USER_OBJECT_ID \
  --role "Contributor" \
  --scope "/subscriptions/$SUBSCRIPTION_ID/resourceGroups/$RESOURCE_GROUP"

az role assignment create \
  --assignee $USER_OBJECT_ID \
  --role "Key Vault Secrets Officer" \
  --scope "/subscriptions/$SUBSCRIPTION_ID/resourceGroups/$RESOURCE_GROUP"

az role assignment create \
  --assignee $USER_OBJECT_ID \
  --role "Storage Blob Data Contributor" \
  --scope "/subscriptions/$SUBSCRIPTION_ID/resourceGroups/$RESOURCE_GROUP"
```

### OAuth Consent

On first login, you'll see a consent screen requesting permissions like:
- **GCP**: "See, edit, configure, and delete your Google Cloud data"
- **Azure**: "Access Azure Service Management" plus storage and Key Vault scopes

This broad permission is necessary because the app manages VMs, storage, and secrets on your behalf. The app only uses these permissions for agent-related operations visible in your audit log.