/* SendBOX - フロントエンド */
(() => {
  "use strict";

  const MAX_TOTAL = 512 * 1024 * 1024; // 512MB
  const MAX_FILES = 50;

  const $ = (id) => document.getElementById(id);

  const fmtSize = (n) => {
    if (n < 1024) return `${n} B`;
    const units = ["KB", "MB", "GB"];
    let v = n;
    for (const u of units) {
      v /= 1024;
      if (v < 1024 || u === "GB") return `${v.toFixed(1)} ${u}`;
    }
  };

  /* ---------------- コピー機能 (アップロード結果 / DLページ共通) ---------------- */

  document.querySelectorAll("[data-copy-target]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const input = $(btn.dataset.copyTarget);
      if (!input) return;
      try {
        await navigator.clipboard.writeText(input.value);
      } catch {
        input.select();
        input.setSelectionRange(0, 99999);
        document.execCommand("copy"); // http 環境向けフォールバック
      }
      const original = btn.textContent;
      btn.textContent = "コピーしました";
      btn.classList.add("copied");
      setTimeout(() => {
        btn.textContent = original;
        btn.classList.remove("copied");
      }, 1600);
    });
  });

  /* ---------------- ここから先はアップロード画面のみ ---------------- */

  const dropzone = $("dropzone");
  if (!dropzone) return;

  const fileInput = $("file-input");
  const folderInput = $("folder-input");
  const folderSelectBtn = $("folder-select-btn");
  const folderHint = $("folder-hint");
  const fileList = $("file-list");
  const totalSizeEl = $("total-size");
  const zipBtn = $("zip-files-btn");
  const uploadBtn = $("upload-btn");
  const passwordEl = $("password");
  const progress = $("progress");
  const progressBar = $("progress-bar");
  const progressText = $("progress-text");
  const errorEl = $("upload-error");

  let files = [];
  let uploading = false;
  let zipping = false;

  const showError = (msg) => {
    errorEl.textContent = msg;
    errorEl.hidden = false;
  };
  const clearError = () => {
    errorEl.hidden = true;
    errorEl.textContent = "";
  };

  const totalSize = () => files.reduce((sum, f) => sum + f.size, 0);

  // フォルダ経由で追加されたファイルは webkitRelativePath / relPath を持つ
  const relPath = (f) => f.relPath || f.webkitRelativePath || f.name;
  const hasFolder = () => files.some((f) => relPath(f).includes("/"));

  const render = () => {
    fileList.textContent = "";
    files.forEach((f, i) => {
      const li = document.createElement("li");

      const name = document.createElement("span");
      name.className = "f-name";
      const path = relPath(f);
      name.textContent = path; // textContent なので XSS 安全
      name.title = path;

      const size = document.createElement("span");
      size.className = "f-size";
      size.textContent = fmtSize(f.size);

      const remove = document.createElement("button");
      remove.type = "button";
      remove.className = "f-remove";
      remove.textContent = "✕";
      remove.setAttribute("aria-label", `${path} を削除`);
      remove.addEventListener("click", () => {
        if (uploading || zipping) return;
        files.splice(i, 1);
        render();
      });

      li.append(name, size, remove);
      fileList.appendChild(li);
    });

    const total = totalSize();
    const over = total > MAX_TOTAL;
    const folderPresent = hasFolder();
    totalSizeEl.hidden = files.length === 0;
    totalSizeEl.classList.toggle("over", over);
    totalSizeEl.textContent = files.length
      ? `合計: ${fmtSize(total)} / 512.0 MB（${files.length} ファイル）` +
        (over ? " — 上限を超えています" : "")
      : "";

    uploadBtn.disabled = files.length === 0 || over || uploading || folderPresent;
    uploadBtn.textContent =
      files.length >= 2 ? "ZIP にまとめてアップロード" : "アップロード";

    const zipEligible = files.length >= 2 || folderPresent;
    zipBtn.hidden = !zipEligible || uploading;
    zipBtn.disabled = zipping;
    zipBtn.textContent = zipping ? "ZIP作成中…" : "選択したファイルをZIPにまとめる";

    folderHint.hidden = !folderPresent || uploading;
  };

  const addFiles = (list) => {
    clearError();
    for (const f of list) {
      const key = `${relPath(f)}|${f.size}|${f.lastModified}`;
      const dup = files.some((x) => `${relPath(x)}|${x.size}|${x.lastModified}` === key);
      if (dup) continue;
      if (files.length >= MAX_FILES) {
        showError(`一度にアップロードできるのは ${MAX_FILES} ファイルまでです。`);
        break;
      }
      files.push(f);
    }
    render();
  };

  /* ---- ファイル選択 / ドラッグ＆ドロップ ---- */

  dropzone.addEventListener("click", () => !uploading && !zipping && fileInput.click());
  dropzone.addEventListener("keydown", (e) => {
    if ((e.key === "Enter" || e.key === " ") && !uploading && !zipping) {
      e.preventDefault();
      fileInput.click();
    }
  });

  fileInput.addEventListener("change", () => {
    addFiles(fileInput.files);
    fileInput.value = ""; // 同じファイルを再選択できるように
  });

  folderSelectBtn.addEventListener("click", (e) => {
    e.stopPropagation();
    if (!uploading && !zipping) folderInput.click();
  });

  folderInput.addEventListener("change", () => {
    addFiles(folderInput.files);
    folderInput.value = "";
  });

  // フォルダエントリを再帰的にたどり、相対パス付きの File 配列を作る
  const readEntry = (entry, base) =>
    new Promise((resolve) => {
      if (entry.isFile) {
        entry.file((file) => {
          const path = base + file.name;
          try {
            Object.defineProperty(file, "relPath", { value: path, configurable: true });
          } catch {
            file.relPath = path;
          }
          resolve([file]);
        }, () => resolve([]));
        return;
      }
      if (entry.isDirectory) {
        const reader = entry.createReader();
        const all = [];
        const readBatch = () => {
          reader.readEntries(async (batch) => {
            if (!batch.length) {
              const nested = await Promise.all(
                all.map((child) => readEntry(child, base + entry.name + "/"))
              );
              resolve(nested.flat());
              return;
            }
            all.push(...batch);
            readBatch(); // readEntries は1回で全件返らない場合があるため繰り返す
          }, () => resolve([]));
        };
        readBatch();
        return;
      }
      resolve([]);
    });

  const filesFromDataTransfer = async (dataTransfer) => {
    const items = dataTransfer?.items;
    if (items && items.length && "webkitGetAsEntry" in items[0]) {
      const entries = Array.from(items)
        .map((it) => it.webkitGetAsEntry && it.webkitGetAsEntry())
        .filter(Boolean);
      if (entries.length) {
        const groups = await Promise.all(entries.map((entry) => readEntry(entry, "")));
        return groups.flat();
      }
    }
    return dataTransfer?.files ? Array.from(dataTransfer.files) : [];
  };

  ["dragenter", "dragover"].forEach((ev) =>
    dropzone.addEventListener(ev, (e) => {
      e.preventDefault();
      if (!uploading && !zipping) dropzone.classList.add("dragover");
    })
  );
  ["dragleave", "drop"].forEach((ev) =>
    dropzone.addEventListener(ev, (e) => {
      e.preventDefault();
      dropzone.classList.remove("dragover");
    })
  );
  dropzone.addEventListener("drop", async (e) => {
    if (uploading || zipping || !e.dataTransfer) return;
    const dropped = await filesFromDataTransfer(e.dataTransfer);
    if (dropped.length) addFiles(dropped);
  });

  // ページ全体へのドロップでブラウザがファイルを開いてしまうのを防止
  ["dragover", "drop"].forEach((ev) =>
    window.addEventListener(ev, (e) => e.preventDefault())
  );

  /* ---- 複数ファイルをZIPにまとめる ---- */

  zipBtn.addEventListener("click", async () => {
    if (zipping || uploading || (files.length < 2 && !hasFolder())) return;

    clearError();
    zipping = true;
    render();

    try {
      if (typeof JSZip === "undefined") {
        throw new Error("ZIP機能の読み込みに失敗しました。ページを再読み込みしてください。");
      }

      const zip = new JSZip();
      const usedNames = new Set();

      for (const f of files) {
        const original = relPath(f);
        let name = original;
        let n = 1;
        while (usedNames.has(name)) {
          const dot = original.lastIndexOf(".");
          name =
            dot > 0
              ? `${original.slice(0, dot)} (${n})${original.slice(dot)}`
              : `${original} (${n})`;
          n++;
        }
        usedNames.add(name);
        zip.file(name, f);
      }

      const blob = await zip.generateAsync({ type: "blob", compression: "DEFLATE" });
      const stamp = new Date()
        .toISOString()
        .replace(/[-:]/g, "")
        .replace(/\..+/, "")
        .replace("T", "_");
      const zipFile = new File([blob], `SendBOX_${stamp}.zip`, {
        type: "application/zip",
      });

      files = [zipFile];
    } catch (err) {
      showError(err?.message || "ZIPの作成に失敗しました。");
    } finally {
      zipping = false;
      render();
    }
  });

  /* ---- アップロード ---- */

  const setProgress = (loaded, total) => {
    const pct = total ? Math.floor((loaded / total) * 100) : 0;
    progressBar.style.width = `${pct}%`;
    progressText.textContent = `${pct}%（${fmtSize(loaded)} / ${fmtSize(total)}）`;
  };

  const showResult = (res) => {
    $("upload-card").hidden = true;
    const card = $("result-card");
    $("result-name").textContent = res.name;
    $("result-meta").textContent =
      `${fmtSize(res.size)}` + (res.protected ? "・パスワード保護あり" : "");
    $("result-link").value = res.url;
    $("result-expiry").textContent =
      `このリンクは ${new Date(res.expires_at * 1000).toLocaleString("ja-JP")} まで有効です（3日間）。`;
    card.hidden = false;
    card.scrollIntoView({ behavior: "smooth", block: "start" });
  };

  uploadBtn.addEventListener("click", () => {
    if (uploading || files.length === 0) return;
    if (totalSize() > MAX_TOTAL) {
      showError("合計サイズが 512MB を超えています。");
      return;
    }

    clearError();
    uploading = true;
    uploadBtn.disabled = true;
    uploadBtn.textContent = "アップロード中…";
    progress.hidden = false;
    setProgress(0, totalSize());

    const fd = new FormData();
    files.forEach((f) => fd.append("files", f, f.name));
    fd.append("password", passwordEl.value);

    const xhr = new XMLHttpRequest();
    xhr.open("POST", "/upload");
    xhr.responseType = "json";

    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable) setProgress(e.loaded, e.total);
    };

    const fail = (msg) => {
      uploading = false;
      progress.hidden = true;
      showError(msg);
      render();
    };

    xhr.onload = () => {
      if (xhr.status === 200 && xhr.response?.url) {
        showResult(xhr.response);
      } else {
        fail(xhr.response?.error || "アップロードに失敗しました。");
      }
    };
    xhr.onerror = () => fail("通信エラーが発生しました。接続を確認してください。");
    xhr.ontimeout = () => fail("タイムアウトしました。もう一度お試しください。");

    xhr.send(fd);
  });

  render();
})();
