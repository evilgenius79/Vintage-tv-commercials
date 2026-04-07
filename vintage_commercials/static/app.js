/* Vintage TV Commercials - Frontend JavaScript */

document.addEventListener("DOMContentLoaded", () => {
    initDownloadButtons();
});

/* ===== Download Handling ===== */
function initDownloadButtons() {
    document.querySelectorAll(".download-btn").forEach(btn => {
        btn.addEventListener("click", (e) => {
            e.preventDefault();
            e.stopPropagation();
            const sourceUrl = btn.dataset.sourceUrl;
            const title = btn.dataset.title;
            const videoId = btn.dataset.videoId;
            startDownload(sourceUrl, title, videoId, btn);
        });
    });
}

async function startDownload(sourceUrl, title, videoId, btn) {
    // Replace button with status indicator
    const status = document.createElement("span");
    status.className = "download-status downloading";
    status.innerHTML = '<span class="spinner"></span> Downloading...';
    btn.replaceWith(status);

    try {
        const resp = await fetch("/api/download", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ source_url: sourceUrl, title: title }),
        });

        if (!resp.ok) {
            status.className = "download-status failed";
            status.textContent = "Failed to start download";
            return;
        }

        // Poll for completion
        pollDownloadStatus(sourceUrl, videoId, status);
    } catch (err) {
        status.className = "download-status failed";
        status.textContent = "Network error";
    }
}

async function pollDownloadStatus(sourceUrl, videoId, statusEl) {
    const maxAttempts = 120; // 10 minutes at 5s intervals
    let attempts = 0;

    const poll = async () => {
        attempts++;
        if (attempts > maxAttempts) {
            statusEl.className = "download-status failed";
            statusEl.textContent = "Download timed out";
            return;
        }

        try {
            const resp = await fetch(`/api/download/status?source_url=${encodeURIComponent(sourceUrl)}`);
            const data = await resp.json();

            if (data.status === "complete") {
                statusEl.className = "download-status complete";
                statusEl.textContent = "Downloaded!";
                // Reload after a moment to show the video player
                if (videoId) {
                    setTimeout(() => window.location.reload(), 1500);
                }
                return;
            }

            if (data.status === "failed") {
                statusEl.className = "download-status failed";
                statusEl.textContent = "Download failed";
                return;
            }

            // Still downloading — poll again
            setTimeout(poll, 5000);
        } catch {
            setTimeout(poll, 5000);
        }
    };

    setTimeout(poll, 3000); // First check after 3s
}
