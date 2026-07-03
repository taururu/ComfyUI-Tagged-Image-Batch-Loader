import { app } from "../../../scripts/app.js";
import { api } from "../../../scripts/api.js";

function getWidgetValue(node, name) {
    const w = node.widgets?.find((w) => w.name === name);
    return w ? w.value : null;
}

function setWidgetValue(node, name, value) {
    const w = node.widgets?.find((w) => w.name === name);
    if (w) {
        w.value = value;
        node.setDirtyCanvas(true);
    }
}

function showPreviewModal(entries, currentExcluded, onApply) {
    const overlay = document.createElement("div");
    overlay.style.cssText = [
        "position:fixed", "top:0", "left:0", "width:100%", "height:100%",
        "background:rgba(0,0,0,0.75)", "z-index:9999",
        "display:flex", "align-items:center", "justify-content:center",
    ].join(";");

    const dialog = document.createElement("div");
    dialog.style.cssText = [
        "background:#1e1e1e", "color:#ddd", "border-radius:8px",
        "padding:16px", "width:700px", "max-width:90vw",
        "max-height:85vh", "display:flex", "flex-direction:column",
        "gap:10px", "font-family:sans-serif", "font-size:13px",
        "box-shadow:0 4px 24px rgba(0,0,0,0.8)",
    ].join(";");

    const header = document.createElement("div");
    header.style.cssText = "font-size:15px;font-weight:bold;border-bottom:1px solid #444;padding-bottom:8px;";
    header.textContent = "CSV Preview  (" + entries.length + " entries)";

    const list = document.createElement("div");
    list.style.cssText = "overflow-y:auto;flex:1;display:flex;flex-direction:column;gap:4px;min-height:0;";

    entries.forEach((entry) => {
        const row = document.createElement("div");
        row.style.cssText = [
            "display:flex", "align-items:center", "gap:8px",
            "padding:4px 6px", "border-radius:4px", "background:#2a2a2a",
        ].join(";");

        const cb = document.createElement("input");
        cb.type = "checkbox";
        cb.checked = !currentExcluded.has(entry.filename);
        cb.dataset.filename = entry.filename;
        cb.style.cssText = "width:16px;height:16px;flex-shrink:0;cursor:pointer;";

        const thumbStyle = "width:48px;height:48px;object-fit:cover;border-radius:3px;background:#333;flex-shrink:0;";

        const mainImg = document.createElement("img");
        mainImg.style.cssText = thumbStyle;
        if (entry.main_thumb) {
            mainImg.src = "data:image/jpeg;base64," + entry.main_thumb;
        }
        mainImg.title = entry.main_exists ? entry.filename : "(missing)";

        const secImg = document.createElement("img");
        secImg.style.cssText = thumbStyle;
        if (entry.secondary_thumb) {
            secImg.src = "data:image/jpeg;base64," + entry.secondary_thumb;
        }
        secImg.title = entry.secondary_exists ? entry.secondary_filename : "(missing)";

        const info = document.createElement("span");
        info.style.cssText = "flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;";
        const tagsStr = entry.tags.length ? "  [" + entry.tags.join(", ") + "]" : "";
        const prefix = !entry.main_exists ? "⚠ " : (!entry.secondary_exists ? "△ " : "");
        info.textContent = prefix + entry.filename + tagsStr;
        info.title = entry.filename + tagsStr;
        if (!entry.main_exists) {
            info.style.color = "#f66";
        } else if (!entry.secondary_exists) {
            info.style.color = "#fa0";
        }

        row.appendChild(cb);
        row.appendChild(mainImg);
        row.appendChild(secImg);
        row.appendChild(info);
        list.appendChild(row);
    });

    const btnRow = document.createElement("div");
    btnRow.style.cssText = "display:flex;gap:8px;justify-content:flex-end;border-top:1px solid #444;padding-top:8px;flex-shrink:0;";

    function makeBtn(label, bg) {
        const btn = document.createElement("button");
        btn.textContent = label;
        btn.style.cssText = "padding:5px 12px;background:" + bg + ";color:#ddd;border:none;border-radius:4px;cursor:pointer;";
        return btn;
    }

    const selectAll  = makeBtn("Select All",  "#444");
    const selectNone = makeBtn("Select None", "#444");
    const closeBtn   = makeBtn("Close",       "#444");
    const applyBtn   = makeBtn("Apply",       "#4a7abb");
    applyBtn.style.fontWeight = "bold";
    applyBtn.style.color = "#fff";

    selectAll.onclick  = () => list.querySelectorAll("input[type=checkbox]").forEach((c) => (c.checked = true));
    selectNone.onclick = () => list.querySelectorAll("input[type=checkbox]").forEach((c) => (c.checked = false));
    closeBtn.onclick   = () => document.body.removeChild(overlay);

    applyBtn.onclick = () => {
        const newExcluded = new Set();
        list.querySelectorAll("input[type=checkbox]").forEach((c) => {
            if (!c.checked) newExcluded.add(c.dataset.filename);
        });
        onApply(newExcluded);
        document.body.removeChild(overlay);
    };

    overlay.addEventListener("click", (e) => {
        if (e.target === overlay) document.body.removeChild(overlay);
    });

    btnRow.appendChild(selectAll);
    btnRow.appendChild(selectNone);
    btnRow.appendChild(closeBtn);
    btnRow.appendChild(applyBtn);

    dialog.appendChild(header);
    dialog.appendChild(list);
    dialog.appendChild(btnRow);
    overlay.appendChild(dialog);
    document.body.appendChild(overlay);
}

app.registerExtension({
    name: "taururu.DualLoaderPreview",

    nodeCreated(node) {
        if (node.comfyClass !== "TaggedImageDualLoader") return;

        node.addWidget("button", "Preview / Reload CSV", null, async () => {
            const path             = getWidgetValue(node, "path")             ?? "";
            const csv_filename     = getWidgetValue(node, "csv_filename")     ?? "image_tags.csv";
            const secondary_suffix = getWidgetValue(node, "secondary_suffix") ?? "_l";

            let currentExcluded = new Set();
            try {
                const raw = getWidgetValue(node, "excluded_files") ?? "[]";
                currentExcluded = new Set(JSON.parse(raw));
            } catch (_) {}

            let entries;
            try {
                const params = new URLSearchParams({ path, csv_filename, secondary_suffix });
                const resp = await api.fetchApi("/taururu/dual_loader/preview?" + params.toString());
                if (!resp.ok) {
                    const err = await resp.json().catch(() => ({ error: resp.statusText }));
                    alert("Preview error: " + (err.error ?? resp.statusText));
                    return;
                }
                entries = await resp.json();
            } catch (e) {
                alert("Failed to fetch preview: " + e.message);
                return;
            }

            if (entries.length === 0) {
                alert("No entries found in CSV.");
                return;
            }

            showPreviewModal(entries, currentExcluded, (newExcluded) => {
                setWidgetValue(node, "excluded_files", JSON.stringify([...newExcluded]));
            });
        });
    },
});
