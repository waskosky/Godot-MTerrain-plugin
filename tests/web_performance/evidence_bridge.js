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
    addEventListener(
        "unhandledrejection",
        (event) => pageErrors.push(String(event.reason)),
    );

    const frameSamples = [];
    let lastFrame;
    const collectFrame = (now) => {
        if (lastFrame !== undefined && frameSamples.length < 50000) {
            frameSamples.push({ at: now, delta: now - lastFrame });
        }
        lastFrame = now;
        requestAnimationFrame(collectFrame);
    };
    requestAnimationFrame(collectFrame);

    const rendererProbe = () => {
        const canvas = document.querySelector("canvas");
        const gl = canvas ? canvas.getContext("webgl2") : null;
        if (!gl) {
            return { ok: false, reason: "webgl2_context_unavailable" };
        }
        const debugInfo = gl.getExtension("WEBGL_debug_renderer_info");
        const pixels = new Uint8Array(canvas.width * canvas.height * 4);
        gl.readPixels(0, 0, canvas.width, canvas.height, gl.RGBA, gl.UNSIGNED_BYTE, pixels);
        const buckets = new Set();
        for (let index = 0; index < pixels.length; index += 4) {
            buckets.add(
                `${pixels[index] >> 4},${pixels[index + 1] >> 4},${pixels[index + 2] >> 4}`,
            );
        }
        return {
            ok: true,
            color_bucket_count: buckets.size,
            renderer: debugInfo
                ? gl.getParameter(debugInfo.UNMASKED_RENDERER_WEBGL)
                : gl.getParameter(gl.RENDERER),
            vendor: debugInfo
                ? gl.getParameter(debugInfo.UNMASKED_VENDOR_WEBGL)
                : gl.getParameter(gl.VENDOR),
            webgl_error: gl.getError(),
        };
    };

    const resourceRecords = () => performance.getEntriesByType("resource").map((entry) => {
        let name = entry.name;
        try {
            const path = new URL(entry.name).pathname.split("/");
            name = path[path.length - 1] || "index.html";
        } catch (_error) {
            name = "unparsed-resource";
        }
        return {
            name,
            duration_ms: entry.duration,
            transfer_size: entry.transferSize,
            encoded_body_size: entry.encodedBodySize,
            decoded_body_size: entry.decodedBodySize,
            response_status: Number(entry.responseStatus || 0),
        };
    });

    const installDownload = (payload) => {
        const button = document.createElement("button");
        button.textContent = "Download MTerrain evidence";
        button.id = "mterrain-evidence-download";
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
            link.download = "mterrain-browser-capture.json";
            link.click();
            setTimeout(() => URL.revokeObjectURL(link.href), 1000);
        });
        document.body.appendChild(button);
    };

    const originalLog = console.log.bind(console);
    console.log = (...values) => {
        originalLog(...values);
        const text = values.map((value) => String(value)).join(" ");
        const marker = "MTERRAIN_WEB_PERFORMANCE_OK";
        if (
            !text.includes(marker)
            || globalThis.__mterrainEvidencePayload
            || globalThis.__mterrainEvidencePending
        ) {
            return;
        }
        globalThis.__mterrainEvidencePending = true;
        setTimeout(async () => {
            try {
                const fixture = JSON.parse(text.split(marker, 2)[1].trim());
                const context = await fetch("mterrain_performance_context.json", {
                    cache: "no-store",
                }).then((response) => {
                    if (!response.ok) {
                        throw new Error(`performance context HTTP ${response.status}`);
                    }
                    return response.json();
                });
                const start = Number(globalThis.__mterrainTraversalStart || 0);
                const end = Number(
                    globalThis.__mterrainTraversalEnd || performance.now(),
                );
                const payload = {
                    schema: "mterrain-browser-capture-v1",
                    captured_at: new Date().toISOString(),
                    context,
                    fixture,
                    timing: {
                        traversal_start_ms: start,
                        traversal_end_ms: end,
                        startup_ms: start,
                        frame_samples_ms: frameSamples
                            .filter((sample) => sample.at >= start && sample.at <= end)
                            .map((sample) => sample.delta),
                    },
                    environment: {
                        user_agent: navigator.userAgent,
                        navigator_platform: navigator.platform,
                        viewport: {
                            width: window.innerWidth,
                            height: window.innerHeight,
                            device_pixel_ratio: window.devicePixelRatio,
                        },
                        javascript_heap_bytes: performance.memory
                            ? performance.memory.usedJSHeapSize
                            : null,
                    ...rendererProbe(),
                },
                resources: resourceRecords(),
                console_errors: consoleErrors,
                page_errors: pageErrors,
            };
                globalThis.__mterrainEvidencePayload = payload;
                installDownload(payload);
            } catch (error) {
                originalLog("MTERRAIN_EVIDENCE_BRIDGE_FAILED", String(error));
            }
        }, 0);
    };
})();
