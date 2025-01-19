# Branching Strategy

## Create the Main Branches

- **`main`**: This is your stable, production-ready branch.
- **`develop`**: The main branch where all feature branches are merged after testing.

### Commands to Create These Branches:
```bash
# Initialize a new Git repository
git init              
# Rename the default branch to 'main'
git branch -M main    
# Create and switch to the 'develop' branch
git checkout -b develop
```

---

## Feature Branches

For each new feature or module, create a new branch off the `develop` branch.

### Examples:
- `feature/api-gpt`
- `feature/storage-s3`
- `feature/database-aurora`

### Command to Create a Feature Branch:
```bash
git checkout develop
git checkout -b feature/api-gpt
```

---

## Hotfix Branches

For urgent bug fixes in the production code:

- Branch off `main` and later merge it back into both `main` and `develop`.

### Command for a Hotfix Branch:
```bash
git checkout main
git checkout -b hotfix/critical-issue
```

---

## Merging and Cleanup

1. **After completing a feature branch**, merge it into `develop`.
2. **Once a release is ready**, merge `develop` into `main`.

### Commands to Merge:
```bash
# Merge a feature branch into develop
git checkout develop
git merge feature/api-gpt

# Merge develop into main for release
git checkout main
git merge develop
```

---

# Feature Branch Workflow

## **Understanding Feature Branch Workflow**

### Create a Feature Branch
When you start working on a specific feature, such as GPT API integration, you create a new branch from `develop`.

**Example:**
```bash
git checkout develop
git checkout -b feature/api-gpt
```
This isolates your work so the `develop` and `main` branches remain stable.

---

### Work Incrementally and Push Regularly
- **You don't need to finish all features before pushing.**
- Push your progress on the feature branch (`feature/api-gpt`) to the remote repository regularly to:
  - Save your work on the cloud.
  - Share your progress with collaborators or make it available for reviews.

**Example Commands:**
```bash
git add .
git commit -m "Initial GPT API integration"
git push origin feature/api-gpt
```

---

## **When to Merge a Feature Branch**

### 1. Finish the Feature
Complete the feature (e.g., the GPT API integration) with all necessary functionality and basic testing.

### 2. Create a Pull Request
Once you finish the feature, you create a **pull request (PR)** to merge `feature/api-gpt` into `develop`.
- The pull request allows you (or your collaborators) to:
  - Review the code.
  - Run additional tests.
  - Ensure the feature doesn’t introduce bugs or break existing functionality.

### 3. Merge the Branch
After the pull request is approved and the feature is confirmed to work, merge the branch:
```bash
git checkout develop
git merge feature/api-gpt
```

### 4. Delete the Feature Branch
Once merged, delete the `feature/api-gpt` branch locally and remotely to keep your repository clean:
```bash
git branch -d feature/api-gpt        # Delete locally
git push origin --delete feature/api-gpt  # Delete remotely
```

---

## **Key Concept: Only Push `develop` or `main` When Stable**

### Push to `develop`:
The `develop` branch serves as the primary integration branch where all features are combined. Once you’ve merged your feature branch into `develop`, push the updated `develop` branch to the remote repository:
```bash
git push origin develop
```

### Push to `main`:
Only when all features are complete and tested, merge `develop` into `main` for release:
```bash
git checkout main
git merge develop
git push origin main
```

---

## **Why This Workflow?**

1. **Isolation**: Each feature is isolated in its branch, so other features or collaborators are unaffected.
2. **Incremental Progress**: You can push partial work to the remote repository without affecting the main codebase.
3. **Collaborative Reviews**: Pull requests allow for feedback and testing before merging features.
4. **Stable `main` Branch**: The `main` branch always represents production-ready code.

---

## **Example Workflow for `feature/api-gpt`**

### Create and Start the Feature Branch:
```bash
git checkout develop
git checkout -b feature/api-gpt
```

### Work on GPT API Integration:
- Write code to connect to the GPT API.
- Test your progress locally.

### Commit and Push Regularly:
```bash
git add .
git commit -m "Add basic GPT API integration"
git push origin feature/api-gpt
```

### Open a Pull Request:
Once you finish and test the feature, open a pull request to merge `feature/api-gpt` into `develop`.

### Review and Merge:
After review and testing, merge the branch into `develop`.

### Delete the Feature Branch:
```bash
git branch -d feature/api-gpt
git push origin --delete feature/api-gpt
```

---

## **Summary**
- You **don’t need to finish all features before pushing**. Instead:
  1. Work on one feature branch at a time.
  2. Push your progress to the remote feature branch regularly.
  3. Merge completed feature branches into `develop`.
  4. Push `main` only when all features are complete, tested, and production-ready.
