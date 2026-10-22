// Presentation only. Leave native deck links, counts and the scheduler intact.
(() => {
    "use strict";
    const strings = __HOLDUP_STRINGS__;
    const tr = (key, values = {}) => strings[key].replace(/\{(\w+)\}/g, (_, name) => String(values[name]));
    window.HoldUpDecks?.destroy();
    const style = document.createElement("style");
    style.textContent = `
        .holdup-deck-badge {
            display: inline-flex;
            align-items: center;
            gap: .35em;
            margin-inline-start: .65em;
            padding: .15em .55em;
            border: 1px solid #cce4d3;
            border-radius: 999px;
            background: #eaf5ed;
            color: #24633c;
            font-size: .72em;
            font-weight: 600;
            line-height: 1.4;
            vertical-align: middle;
            white-space: nowrap;
            cursor: default;
        }
        .night-mode .holdup-deck-badge, .nightMode .holdup-deck-badge {
            border-color: #355d43;
            background: #233e2d;
            color: #b8e5c6;
        }
        .holdup-deck-badge svg { width: 1em; height: 1em; flex: none; }
    `;
    document.head.append(style);

    window.HoldUpDecks = {
        update(counts) {
            document.querySelectorAll("tr.deck[id]").forEach(row => {
                const cell = row.querySelector("td.decktd");
                if (!cell) return;
                const count = counts[row.id];
                let badge = cell.querySelector(".holdup-deck-badge");
                if (!Number.isSafeInteger(count) || count <= 0 || cell.querySelector("a.filtered")) {
                    badge?.remove();
                    return;
                }
                if (!badge) {
                    badge = document.createElement("span");
                    badge.className = "holdup-deck-badge";
                    badge.setAttribute("role", "status");
                    badge.innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" '
                        + 'stroke-width="1.8" stroke-linecap="round" aria-hidden="true" focusable="false">'
                        + '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/></svg><span></span>';
                    cell.append(badge);
                }
                const text = "HoldUp · " + count;
                if (badge.lastChild.textContent !== text) badge.lastChild.textContent = text;
                badge.title = tr("HoldUp: ready {count} (including subdecks)", {count});
                badge.setAttribute("aria-label", badge.title);
                badge.dataset.count = String(count);
            });
        },
        destroy() {
            style.remove();
            document.querySelectorAll(".holdup-deck-badge").forEach(badge => badge.remove());
        },
    };
})();
