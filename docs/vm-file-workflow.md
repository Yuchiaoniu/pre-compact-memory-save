# VM 生產檔案修改流程

GCP VM 上的生產檔案（public/dashboard.html、public/dashboard02.html 等靜態頁面）
與本機 staging/ 目錄的版本**不一定同步**，VM 版本通常比本機新好幾個 commit。

**每次要修改 VM 上的檔案，必須先從 VM 拉下來，再修，再推上去：**

```powershell
# 1. 先拉（SCP 從 VM 拉到本機 staging/）
$SCP = "C:\WINDOWS\System32\OpenSSH\scp.exe"
$KEY = "$env:USERPROFILE\.ssh\google_compute_engine"
& $SCP -i $KEY -o StrictHostKeyChecking=no `
  "yuchi@<VM_IP>:/home/yuchi/<專案>/public/<檔名>" `
  "C:\Users\yuchi\openspec\changes\<專案>\staging\public\<檔名>"

# 2. 在本機改（Edit 工具）

# 3. 再推回 VM（SCP 上傳）
& $SCP -i $KEY -o StrictHostKeyChecking=no `
  "C:\Users\yuchi\openspec\changes\<專案>\staging\public\<檔名>" `
  "yuchi@<VM_IP>:/home/yuchi/<專案>/public/<檔名>"

# 4. 在 VM 上 push GitHub Pages
& $SSH @OPTS "yuchi@<VM_IP>" "cd /home/yuchi/<專案> && node push_gh.js 'public/<檔名>' 'public/<檔名>' '<commit msg>'"
```

**絕對不可以**直接把本機 staging/ 的舊版本 SCP 上去，那樣會覆蓋 VM 的新版。
