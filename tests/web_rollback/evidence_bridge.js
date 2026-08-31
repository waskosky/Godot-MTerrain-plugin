(() => {
    "use strict";

    const consoleErrors = [];
    const pageErrors = [];
    const originalError = console.error.bind(console);
    console.error = (...values) => {
        consoleErrors.push(values.map((value) => String(value)).join(" "));
        originalError(...values);
    };
    addEventListener("error", (event) => pageErrors.push(String(event.message)));
    addEventListener("unhandledrejection", (event) => pageErrors.push(String(event.reason)));

    const frameProbe = () => {
        const canvas = document.querySelector("canvas");
        const gl = canvas ? canvas.getContext("webgl2") : null;
        if (!canvas || !gl) {
            return { ok: false, reason: "webgl2_context_unavailable" };
        }
        const debugInfo = gl.getExtension("WEBGL_debug_renderer_info");
        const pixels = new Uint8Array(canvas.width * canvas.height * 4);
        gl.readPixels(0, 0, canvas.width, canvas.height, gl.RGBA, gl.UNSIGNED_BYTE, pixels);
        const buckets = new Set();
        for (let index = 0; index < pixels.length; index += 4) {
            buckets.add(`${pixels[index] >> 4},${pixels[index + 1] >> 4},${pixels[index + 2] >> 4}`);
        }
        return {
            ok: gl.getError() === gl.NO_ERROR,
            color_bucket_count: buckets.size,
            renderer: debugInfo
                ? gl.getParameter(debugInfo.UNMASKED_RENDERER_WEBGL)
                : gl.getParameter(gl.RENDERER),
            vendor: debugInfo
                ? gl.getParameter(debugInfo.UNMASKED_VENDOR_WEBGL)
                : gl.getParameter(gl.VENDOR),
        };
    };

    const installDownload = (payload) => {
        const button = document.createElement("button");
        button.textContent = "Download rollback evidence";
        button.id = "mterrain-rollback-evidence-download";
        Object.assign(button.style, {
            position: "fixed",
            right: "12px",
            bottom: "12px",
            zIndex: "2147483647",
            padding: "10px 14px",
        });
        button.addEventListener("click", () => {
            const blob = new Blob(
                [JSON.stringify(payload, null, 2) + "\n"],
                { type: "application/json" },
            );
            const link = document.createElement("a");
            link.href = URL.createObjectURL(blob);
            link.download = `mterrain-rollback-${payload.context.stage}.json`;
            link.click();
            setTimeout(() => URL.revokeObjectURL(link.href), 1000);
        });
        document.body.appendChild(button);
    };

    const originalLog = console.log.bind(console);
    console.log = (...values) => {
        originalLog(...values);
        const text = values.map((value) => String(value)).join(" ");
        if (!text.includes("MTERRAIN_WEB_ROLLBACK_OK") || globalThis.__mterrainRollbackEvidence) {
            return;
        }
        setTimeout(async () => {
            try {
                const context = await fetch("mterrain_rollback_context.json", {
                    cache: "no-store",
                }).then((response) => {
                    if (!response.ok) {
                        throw new Error(`rollback context HTTP ${response.status}`);
                    }
                    return response.json();
                });
                const payload = {
                    schema: "mterrain-browser-rollback-capture-v1",
                    captured_at: new Date().toISOString(),
                    context,
                    success_marker: text,
                    environment: {
                        user_agent: navigator.userAgent,
                        navigator_platform: navigator.platform,
                        viewport: {
                            width: window.innerWidth,
                            height: window.innerHeight,
                            device_pixel_ratio: window.devicePixelRatio,
                        },
                        ...frameProbe(),
                    },
                    console_errors: consoleErrors,
                    page_errors: pageErrors,
                };
                globalThis.__mterrainRollbackEvidence = payload;
                installDownload(payload);
            } catch (error) {
                originalError("MTERRAIN_ROLLBACK_EVIDENCE_BRIDGE_FAILED", String(error));
            }
        }, 1000);
    };
})();
