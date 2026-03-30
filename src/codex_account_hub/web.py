from __future__ import annotations

import json
import re
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from .core import AuthHubError
from .providers import UnifiedAuthHub, normalize_provider_name


INDEX_HTML = """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Agent Account Hub</title>
  <style>
    :root {
      color-scheme: light;
      --bg: #f6eee4;
      --bg-strong: #ecdcca;
      --surface: rgba(255, 248, 240, 0.82);
      --surface-strong: rgba(255, 250, 245, 0.96);
      --surface-soft: rgba(243, 231, 217, 0.72);
      --ink: #1e1916;
      --muted: #6c645b;
      --muted-strong: #81776c;
      --line: rgba(30, 25, 22, 0.12);
      --accent: #165d63;
      --accent-deep: #0d4448;
      --accent-soft: rgba(22, 93, 99, 0.12);
      --accent-strong: rgba(22, 93, 99, 0.22);
      --ember: #ab5d1e;
      --ember-soft: rgba(171, 93, 30, 0.12);
      --ok: #207753;
      --ok-soft: rgba(32, 119, 83, 0.13);
      --warn: #b45309;
      --warn-soft: rgba(180, 83, 9, 0.14);
      --bad: #b42318;
      --bad-soft: rgba(180, 35, 24, 0.14);
      --shadow: 0 28px 80px rgba(67, 47, 28, 0.14);
      --radius-xl: 30px;
      --radius-lg: 24px;
      --radius-md: 18px;
      --radius-sm: 14px;
    }

    * {
      box-sizing: border-box;
    }

    body {
      margin: 0;
      min-height: 100vh;
      font-family: "Avenir Next", "Gill Sans", sans-serif;
      color: var(--ink);
      background:
        radial-gradient(circle at 12% 10%, rgba(22, 93, 99, 0.22), transparent 26%),
        radial-gradient(circle at 88% 12%, rgba(171, 93, 30, 0.16), transparent 28%),
        linear-gradient(135deg, #fbf6ef 0%, #efe2d2 48%, #f6ebdf 100%);
      position: relative;
      overflow-x: hidden;
    }

    body::before {
      content: "";
      position: fixed;
      inset: 0;
      pointer-events: none;
      background:
        linear-gradient(rgba(255, 255, 255, 0.22), rgba(255, 255, 255, 0)),
        repeating-linear-gradient(
          90deg,
          rgba(30, 25, 22, 0.03) 0,
          rgba(30, 25, 22, 0.03) 1px,
          transparent 1px,
          transparent 72px
        );
      mask-image: linear-gradient(to bottom, rgba(0, 0, 0, 0.65), transparent 82%);
    }

    main {
      width: min(1240px, calc(100vw - 32px));
      margin: 0 auto;
      padding: 24px 0 48px;
      display: grid;
      gap: 18px;
      position: relative;
      z-index: 1;
    }

    h1,
    h2,
    h3 {
      margin: 0;
      font-family: "Baskerville", "Iowan Old Style", serif;
      font-weight: 700;
      letter-spacing: -0.03em;
    }

    h1 {
      font-size: clamp(2.4rem, 5vw, 4.4rem);
      line-height: 0.96;
      max-width: 9.5em;
    }

    h2 {
      font-size: 1.55rem;
      line-height: 1.05;
    }

    h3 {
      font-size: 1.24rem;
      line-height: 1.1;
    }

    p {
      margin: 0;
      line-height: 1.55;
    }

    code {
      font-family: "SF Mono", "Menlo", monospace;
      font-size: 0.9rem;
      padding: 0.18rem 0.45rem;
      border-radius: 999px;
      background: rgba(30, 25, 22, 0.06);
      color: var(--ink);
      word-break: break-all;
    }

    button {
      font: inherit;
      border: 0;
      cursor: pointer;
    }

    .panel {
      position: relative;
      overflow: hidden;
      border-radius: var(--radius-xl);
      border: 1px solid var(--line);
      background: linear-gradient(180deg, rgba(255, 255, 255, 0.72), rgba(255, 248, 240, 0.95));
      box-shadow: var(--shadow);
      backdrop-filter: blur(18px);
      animation: rise-in 520ms both;
    }

    .panel::after {
      content: "";
      position: absolute;
      inset: 0;
      pointer-events: none;
      background: linear-gradient(135deg, rgba(255, 255, 255, 0.22), transparent 42%);
    }

    .eyebrow {
      font-size: 0.78rem;
      letter-spacing: 0.18em;
      text-transform: uppercase;
      color: var(--muted);
      margin-bottom: 10px;
    }

    .section-head {
      display: flex;
      justify-content: space-between;
      align-items: start;
      gap: 18px;
      flex-wrap: wrap;
    }

    .section-copy {
      display: grid;
      gap: 6px;
      max-width: 48rem;
    }

    .section-copy p {
      color: var(--muted);
    }

    .topbar {
      padding: 18px 22px;
    }

    .topbar-actions {
      display: flex;
      align-items: center;
      gap: 12px;
      flex-wrap: wrap;
    }

    .provider-tabs {
      display: inline-flex;
      align-items: center;
      gap: 10px;
      flex-wrap: wrap;
    }

    .provider-tab {
      min-height: 42px;
      padding: 0 16px;
      border-radius: 999px;
      color: var(--muted);
      background: rgba(255, 255, 255, 0.76);
      border: 1px solid rgba(30, 25, 22, 0.08);
      font-weight: 650;
    }

    .provider-tab.active {
      color: var(--accent-deep);
      background: rgba(22, 93, 99, 0.12);
      border-color: rgba(22, 93, 99, 0.18);
      box-shadow: 0 10px 24px rgba(13, 68, 72, 0.12);
    }

    .topbar-copy p {
      max-width: 44rem;
    }

    .masthead {
      padding: 30px;
    }

    .masthead-grid {
      display: grid;
      grid-template-columns: minmax(0, 1.45fr) minmax(320px, 0.95fr);
      gap: 20px;
      align-items: stretch;
    }

    .brand-row {
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 14px;
      margin-bottom: 18px;
      flex-wrap: wrap;
    }

    .sync-pill {
      display: inline-flex;
      align-items: center;
      gap: 10px;
      padding: 10px 14px;
      border-radius: 999px;
      background: rgba(255, 255, 255, 0.72);
      border: 1px solid rgba(30, 25, 22, 0.08);
      color: var(--muted);
      font-size: 0.9rem;
    }

    .sync-pill::before {
      content: "";
      width: 10px;
      height: 10px;
      border-radius: 999px;
      background: var(--accent);
      box-shadow: 0 0 0 5px rgba(22, 93, 99, 0.12);
    }

    .sync-pill.syncing::before {
      background: var(--ember);
      box-shadow: 0 0 0 5px rgba(171, 93, 30, 0.12);
      animation: pulse 1s infinite;
    }

    .sync-pill.error::before {
      background: var(--bad);
      box-shadow: 0 0 0 5px rgba(180, 35, 24, 0.14);
    }

    .headline-copy {
      display: grid;
      gap: 14px;
    }

    .headline-copy p {
      max-width: 42rem;
      color: var(--muted);
      font-size: 1.05rem;
    }

    .trust-row {
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      margin-top: 6px;
    }

    .chip {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      gap: 8px;
      padding: 8px 12px;
      border-radius: 999px;
      border: 1px solid transparent;
      font-size: 0.84rem;
      white-space: nowrap;
      background: rgba(255, 255, 255, 0.74);
      color: var(--ink);
    }

    .chip.muted {
      background: rgba(255, 255, 255, 0.66);
      color: var(--muted);
      border-color: rgba(30, 25, 22, 0.07);
    }

    .chip.accent {
      background: var(--accent-soft);
      color: var(--accent-deep);
      border-color: rgba(22, 93, 99, 0.16);
    }

    .chip.good {
      background: var(--ok-soft);
      color: var(--ok);
      border-color: rgba(32, 119, 83, 0.12);
    }

    .chip.warn {
      background: var(--warn-soft);
      color: var(--warn);
      border-color: rgba(180, 83, 9, 0.12);
    }

    .chip.bad {
      background: var(--bad-soft);
      color: var(--bad);
      border-color: rgba(180, 35, 24, 0.14);
    }

    .chip.ember {
      background: var(--ember-soft);
      color: var(--ember);
      border-color: rgba(171, 93, 30, 0.12);
    }

    .hero-actions {
      display: flex;
      align-items: center;
      gap: 14px;
      flex-wrap: wrap;
      margin-top: 8px;
    }

    .button {
      min-height: 46px;
      padding: 0 18px;
      border-radius: 999px;
      transition: transform 140ms ease, box-shadow 140ms ease, opacity 140ms ease, background 140ms ease;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      gap: 8px;
      font-weight: 600;
    }

    .button:hover:not(:disabled) {
      transform: translateY(-1px);
    }

    .button:disabled {
      opacity: 0.45;
      cursor: not-allowed;
      transform: none;
      box-shadow: none;
    }

    .button.primary {
      color: #fff7f0;
      background: linear-gradient(135deg, var(--accent) 0%, var(--accent-deep) 100%);
      box-shadow: 0 14px 30px rgba(13, 68, 72, 0.22);
    }

    .button.secondary {
      color: var(--ink);
      background: rgba(255, 255, 255, 0.76);
      border: 1px solid rgba(30, 25, 22, 0.08);
    }

    .button.ghost {
      color: var(--bad);
      background: rgba(180, 35, 24, 0.08);
      border: 1px solid rgba(180, 35, 24, 0.12);
    }

    .hero-stats {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 14px;
      align-content: start;
    }

    .stat-card {
      padding: 18px;
      border-radius: var(--radius-lg);
      border: 1px solid rgba(30, 25, 22, 0.08);
      background: rgba(255, 255, 255, 0.72);
      display: grid;
      gap: 10px;
      min-height: 138px;
    }

    .stat-card:nth-child(1) {
      background: linear-gradient(180deg, rgba(22, 93, 99, 0.15), rgba(255, 255, 255, 0.84));
    }

    .stat-card:nth-child(2) {
      background: linear-gradient(180deg, rgba(171, 93, 30, 0.14), rgba(255, 255, 255, 0.84));
    }

    .stat-card:nth-child(3) {
      background: linear-gradient(180deg, rgba(32, 119, 83, 0.14), rgba(255, 255, 255, 0.84));
    }

    .stat-card:nth-child(4) {
      background: linear-gradient(180deg, rgba(30, 25, 22, 0.08), rgba(255, 255, 255, 0.84));
    }

    .stat-label {
      font-size: 0.78rem;
      text-transform: uppercase;
      letter-spacing: 0.15em;
      color: var(--muted);
    }

    .stat-value {
      font-size: 1.9rem;
      line-height: 1;
      font-family: "Baskerville", "Iowan Old Style", serif;
      letter-spacing: -0.04em;
      word-break: break-word;
    }

    .stat-caption {
      font-size: 0.95rem;
      color: var(--muted);
    }

    .dashboard-grid {
      display: grid;
      grid-template-columns: minmax(0, 1.4fr) minmax(320px, 0.92fr);
      gap: 18px;
      align-items: start;
    }

    .current-panel,
    .side-panel,
    .slots-panel {
      padding: 24px;
      display: grid;
      gap: 18px;
    }

    .config-panel {
      padding: 24px;
      display: grid;
      gap: 18px;
    }

    .identity-shell {
      display: grid;
      grid-template-columns: auto minmax(0, 1fr);
      gap: 18px;
      padding: 18px;
      border-radius: var(--radius-lg);
      border: 1px solid rgba(22, 93, 99, 0.14);
      background:
        radial-gradient(circle at top right, rgba(22, 93, 99, 0.14), transparent 34%),
        linear-gradient(180deg, rgba(255, 255, 255, 0.88), rgba(247, 240, 231, 0.94));
    }

    .identity-avatar {
      width: 74px;
      height: 74px;
      border-radius: 24px;
      display: grid;
      place-items: center;
      font-size: 1.5rem;
      font-weight: 700;
      color: #fff8ef;
      background: linear-gradient(135deg, var(--accent) 0%, var(--accent-deep) 100%);
      box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.12);
    }

    .identity-copy {
      display: grid;
      gap: 8px;
      min-width: 0;
    }

    .identity-overline {
      font-size: 0.8rem;
      letter-spacing: 0.14em;
      text-transform: uppercase;
      color: var(--muted);
    }

    .identity-title {
      font-size: clamp(1.4rem, 2vw, 2rem);
      line-height: 1.05;
      word-break: break-word;
      font-family: "Baskerville", "Iowan Old Style", serif;
    }

    .identity-subtitle {
      color: var(--muted);
      word-break: break-word;
    }

    .chip-row {
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      align-items: center;
    }

    .detail-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
      gap: 12px;
    }

    .detail-card {
      padding: 14px;
      border-radius: var(--radius-md);
      background: rgba(255, 255, 255, 0.72);
      border: 1px solid rgba(30, 25, 22, 0.07);
      display: grid;
      gap: 6px;
    }

    .detail-label {
      font-size: 0.78rem;
      letter-spacing: 0.12em;
      text-transform: uppercase;
      color: var(--muted);
    }

    .detail-value {
      word-break: break-word;
      color: var(--ink);
    }

    .detail-note {
      color: var(--muted);
      font-size: 0.9rem;
    }

    .meta-note {
      color: var(--muted);
      font-size: 0.95rem;
    }

    .path-stack,
    .guide-list {
      display: grid;
      gap: 12px;
    }

    .path-card,
    .guide-card {
      padding: 16px;
      border-radius: var(--radius-md);
      background: rgba(255, 255, 255, 0.72);
      border: 1px solid rgba(30, 25, 22, 0.07);
      display: grid;
      gap: 8px;
    }

    .path-label,
    .guide-step {
      font-size: 0.78rem;
      text-transform: uppercase;
      letter-spacing: 0.14em;
      color: var(--muted);
    }

    .path-value {
      word-break: break-word;
      font-family: "SF Mono", "Menlo", monospace;
      font-size: 0.92rem;
      color: var(--ink);
    }

    .guide-title {
      font-size: 1rem;
      font-weight: 650;
    }

    .guide-copy {
      color: var(--muted);
      font-size: 0.95rem;
    }

    .summary-row {
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
    }

    .details-panel {
      padding: 0;
    }

    .details-shell {
      margin: 0;
    }

    .details-shell[open] .details-summary {
      border-bottom-color: rgba(30, 25, 22, 0.08);
    }

    .details-summary {
      list-style: none;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      padding: 18px 22px;
      cursor: pointer;
      border-bottom: 1px solid transparent;
    }

    .details-summary::-webkit-details-marker {
      display: none;
    }

    .details-title {
      display: flex;
      align-items: center;
      gap: 10px;
      font-weight: 650;
    }

    .details-body {
      padding: 0 22px 22px;
      display: grid;
      gap: 14px;
    }

    .slots {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(292px, 1fr));
      gap: 16px;
    }

    .config-grid {
      display: grid;
      grid-template-columns: minmax(0, 1.18fr) minmax(300px, 0.92fr);
      gap: 16px;
      align-items: start;
    }

    .config-selector {
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      align-items: center;
    }

    .selector-pill {
      min-height: 40px;
      padding: 0 14px;
      border-radius: 999px;
      border: 1px solid rgba(30, 25, 22, 0.08);
      background: rgba(255, 255, 255, 0.72);
      color: var(--muted);
      font-weight: 650;
      transition: transform 140ms ease, border-color 140ms ease, box-shadow 140ms ease, background 140ms ease;
    }

    .selector-pill:hover {
      transform: translateY(-1px);
      border-color: rgba(22, 93, 99, 0.2);
    }

    .selector-pill.active {
      color: var(--accent-deep);
      background: rgba(22, 93, 99, 0.12);
      border-color: rgba(22, 93, 99, 0.2);
      box-shadow: 0 12px 28px rgba(13, 68, 72, 0.1);
    }

    .config-card {
      padding: 18px;
      border-radius: 26px;
      border: 1px solid rgba(30, 25, 22, 0.08);
      background:
        radial-gradient(circle at top right, rgba(22, 93, 99, 0.08), transparent 34%),
        linear-gradient(180deg, rgba(255, 255, 255, 0.9), rgba(247, 240, 232, 0.98));
      display: grid;
      gap: 16px;
      min-height: 100%;
    }

    .config-card.empty {
      background:
        radial-gradient(circle at top right, rgba(171, 93, 30, 0.08), transparent 35%),
        linear-gradient(180deg, rgba(255, 255, 255, 0.88), rgba(248, 244, 238, 0.98));
    }

    .config-stack,
    .module-stack,
    .selection-stack,
    .preview-stack {
      display: grid;
      gap: 12px;
    }

    .config-hero {
      display: grid;
      grid-template-columns: auto minmax(0, 1fr);
      gap: 14px;
      align-items: start;
    }

    .config-avatar {
      width: 58px;
      height: 58px;
      border-radius: 18px;
      display: grid;
      place-items: center;
      font-size: 1.2rem;
      font-weight: 700;
      color: #fff8ef;
      background: linear-gradient(135deg, var(--accent) 0%, var(--accent-deep) 100%);
    }

    .config-copy {
      display: grid;
      gap: 6px;
      min-width: 0;
    }

    .config-title {
      font-size: 1.45rem;
      line-height: 1.08;
      font-family: "Baskerville", "Iowan Old Style", serif;
      word-break: break-word;
    }

    .config-subtitle {
      color: var(--muted);
      word-break: break-word;
    }

    .module-card {
      padding: 16px;
      border-radius: 20px;
      border: 1px solid rgba(30, 25, 22, 0.08);
      background: rgba(255, 255, 255, 0.74);
      display: grid;
      gap: 12px;
    }

    .module-head {
      display: flex;
      justify-content: space-between;
      align-items: start;
      gap: 12px;
      flex-wrap: wrap;
    }

    .module-copy {
      display: grid;
      gap: 6px;
    }

    .module-title {
      font-size: 1rem;
      font-weight: 650;
    }

    .module-description {
      color: var(--muted);
      font-size: 0.95rem;
      line-height: 1.5;
    }

    .inline-form {
      display: grid;
      gap: 10px;
    }

    .inline-form-row {
      display: flex;
      gap: 10px;
      flex-wrap: wrap;
      align-items: center;
    }

    .inline-form-row .field-input {
      flex: 1 1 220px;
    }

    .empty-state {
      padding: 16px;
      border-radius: 18px;
      border: 1px dashed rgba(30, 25, 22, 0.12);
      background: rgba(255, 255, 255, 0.48);
      color: var(--muted);
      line-height: 1.6;
    }

    .selection-row {
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 12px;
      padding: 14px 16px;
      border-radius: 18px;
      border: 1px solid rgba(30, 25, 22, 0.07);
      background: rgba(255, 255, 255, 0.74);
    }

    .selection-row.disabled {
      opacity: 0.72;
      background: rgba(255, 255, 255, 0.52);
    }

    .selection-copy {
      display: grid;
      gap: 6px;
      min-width: 0;
    }

    .selection-title {
      font-weight: 650;
      word-break: break-word;
    }

    .selection-subtitle {
      color: var(--muted);
      font-size: 0.92rem;
      line-height: 1.45;
      word-break: break-word;
    }

    .mini-usage {
      display: grid;
      gap: 8px;
    }

    .mini-usage-row {
      display: grid;
      gap: 6px;
    }

    .mini-usage-meta {
      display: flex;
      justify-content: space-between;
      gap: 10px;
      color: var(--muted);
      font-size: 0.82rem;
    }

    .slot-card {
      position: relative;
      overflow: hidden;
      padding: 18px;
      border-radius: 26px;
      border: 1px solid rgba(30, 25, 22, 0.08);
      background:
        radial-gradient(circle at top right, rgba(22, 93, 99, 0.1), transparent 35%),
        linear-gradient(180deg, rgba(255, 255, 255, 0.88), rgba(247, 240, 232, 0.98));
      display: grid;
      gap: 14px;
      transform: translateY(0);
      transition: transform 160ms ease, box-shadow 160ms ease, border-color 160ms ease;
      animation: rise-in 520ms both;
      animation-delay: var(--delay, 0ms);
    }

    .slot-card:hover {
      transform: translateY(-2px);
      border-color: rgba(22, 93, 99, 0.18);
      box-shadow: 0 24px 58px rgba(62, 45, 27, 0.12);
    }

    .slot-card.selected {
      border-color: rgba(22, 93, 99, 0.24);
      box-shadow: 0 26px 62px rgba(13, 68, 72, 0.12);
    }

    .slot-card.active {
      border-color: rgba(22, 93, 99, 0.26);
      box-shadow: 0 24px 58px rgba(13, 68, 72, 0.14);
    }

    .slot-card.active::before {
      content: "";
      position: absolute;
      inset: 0 auto auto 0;
      width: 100%;
      height: 4px;
      background: linear-gradient(90deg, var(--accent) 0%, rgba(22, 93, 99, 0.12) 100%);
    }

    .slot-card.empty {
      background:
        radial-gradient(circle at top right, rgba(171, 93, 30, 0.08), transparent 35%),
        linear-gradient(180deg, rgba(255, 255, 255, 0.88), rgba(248, 244, 238, 0.98));
    }

    .slot-top {
      display: flex;
      justify-content: space-between;
      align-items: start;
      gap: 12px;
    }

    .slot-mark {
      width: 54px;
      height: 54px;
      border-radius: 18px;
      display: grid;
      place-items: center;
      font-size: 1.18rem;
      font-weight: 700;
      color: var(--accent-deep);
      background: rgba(22, 93, 99, 0.12);
      border: 1px solid rgba(22, 93, 99, 0.12);
    }

    .slot-card.empty .slot-mark {
      color: var(--ember);
      background: rgba(171, 93, 30, 0.1);
      border-color: rgba(171, 93, 30, 0.12);
    }

    .slot-title-wrap {
      display: grid;
      gap: 6px;
      min-width: 0;
    }

    .slot-id {
      color: var(--muted);
      font-size: 0.9rem;
    }

    .slot-identity {
      font-family: "Baskerville", "Iowan Old Style", serif;
      font-size: 1.45rem;
      line-height: 1.08;
      word-break: break-word;
    }

    .slot-caption {
      color: var(--muted);
      font-size: 0.96rem;
    }

    .slot-hint {
      color: var(--muted-strong);
      font-size: 0.88rem;
      line-height: 1.45;
    }

    .slot-kpis {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 10px;
    }

    .slot-kpi {
      padding: 12px;
      border-radius: 16px;
      background: rgba(255, 255, 255, 0.72);
      border: 1px solid rgba(30, 25, 22, 0.07);
      display: grid;
      gap: 4px;
    }

    .slot-kpi-label {
      font-size: 0.74rem;
      letter-spacing: 0.12em;
      text-transform: uppercase;
      color: var(--muted);
    }

    .slot-kpi-value {
      color: var(--ink);
      word-break: break-word;
    }

    .slot-facts {
      display: grid;
      gap: 10px;
    }

    .fact-row {
      display: flex;
      justify-content: space-between;
      gap: 16px;
      font-size: 0.95rem;
      border-bottom: 1px dashed rgba(30, 25, 22, 0.08);
      padding-bottom: 10px;
    }

    .fact-row:last-child {
      border-bottom: 0;
      padding-bottom: 0;
    }

    .fact-label {
      color: var(--muted);
      flex: 0 0 auto;
    }

    .fact-value {
      text-align: right;
      word-break: break-word;
    }

    .slot-actions {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(120px, 1fr));
      gap: 10px;
      margin-top: 4px;
    }

    .token-details {
      border-top: 1px dashed rgba(30, 25, 22, 0.08);
      padding-top: 12px;
      display: grid;
      gap: 10px;
    }

    .token-summary {
      list-style: none;
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 12px;
      cursor: pointer;
      color: var(--ink);
      font-weight: 600;
    }

    .token-summary::-webkit-details-marker {
      display: none;
    }

    .token-summary-note {
      color: var(--muted);
      font-size: 0.88rem;
      font-weight: 500;
      text-align: right;
    }

    .token-body {
      padding-top: 2px;
    }

    .token-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
      gap: 12px;
    }

    .usage-visuals {
      display: grid;
      gap: 10px;
    }

    .usage-bar {
      padding: 12px 14px;
      border-radius: 18px;
      border: 1px solid rgba(30, 25, 22, 0.07);
      background: rgba(255, 255, 255, 0.74);
      display: grid;
      gap: 8px;
    }

    .usage-bar-meta {
      display: flex;
      justify-content: space-between;
      align-items: baseline;
      gap: 12px;
      flex-wrap: wrap;
    }

    .usage-bar-label {
      font-size: 0.78rem;
      text-transform: uppercase;
      letter-spacing: 0.14em;
      color: var(--muted);
    }

    .usage-bar-value {
      font-family: "Baskerville", "Iowan Old Style", serif;
      font-size: 1.2rem;
      line-height: 1;
    }

    .usage-bar-note {
      font-size: 0.9rem;
      color: var(--muted);
    }

    .usage-track {
      height: 11px;
      border-radius: 999px;
      background: rgba(30, 25, 22, 0.09);
      overflow: hidden;
    }

    .usage-fill {
      height: 100%;
      width: var(--percent, 0%);
      min-width: 8px;
      border-radius: 999px;
      transition: width 240ms ease;
    }

    .usage-fill.good {
      background: linear-gradient(90deg, rgba(32, 119, 83, 0.78), rgba(32, 119, 83, 1));
    }

    .usage-fill.warn {
      background: linear-gradient(90deg, rgba(180, 83, 9, 0.72), rgba(180, 83, 9, 1));
    }

    .usage-fill.bad {
      background: linear-gradient(90deg, rgba(180, 35, 24, 0.72), rgba(180, 35, 24, 1));
    }

    .usage-fill.muted {
      background: linear-gradient(90deg, rgba(108, 100, 91, 0.34), rgba(108, 100, 91, 0.5));
    }

    .status {
      position: fixed;
      right: 18px;
      bottom: 18px;
      max-width: min(420px, calc(100vw - 36px));
      padding: 14px 18px;
      border-radius: 18px;
      color: #fff9f2;
      background: rgba(20, 18, 16, 0.92);
      box-shadow: 0 24px 58px rgba(31, 23, 18, 0.26);
      opacity: 0;
      transform: translateY(14px);
      transition: opacity 160ms ease, transform 160ms ease;
      pointer-events: none;
      z-index: 3;
    }

    .status.show {
      opacity: 1;
      transform: translateY(0);
    }

    .status.error {
      background: rgba(133, 26, 18, 0.94);
    }

    .empty-copy {
      color: var(--muted);
    }

    [hidden] {
      display: none !important;
    }

    .modal-backdrop {
      position: fixed;
      inset: 0;
      z-index: 4;
      background: rgba(23, 18, 15, 0.42);
      backdrop-filter: blur(8px);
      display: grid;
      place-items: center;
      padding: 18px;
    }

    .modal-card {
      width: min(720px, calc(100vw - 24px));
      max-height: min(86vh, 860px);
      overflow: auto;
      padding: 24px;
      border-radius: var(--radius-xl);
      border: 1px solid rgba(30, 25, 22, 0.1);
      background: linear-gradient(180deg, rgba(255, 252, 248, 0.98), rgba(246, 237, 227, 0.98));
      box-shadow: 0 30px 90px rgba(44, 31, 19, 0.28);
      display: grid;
      gap: 18px;
    }

    .modal-head {
      display: grid;
      gap: 8px;
    }

    .modal-copy {
      color: var(--muted);
    }

    .form-grid {
      display: grid;
      gap: 14px;
    }

    .field {
      display: grid;
      gap: 8px;
    }

    .field-label {
      font-size: 0.82rem;
      letter-spacing: 0.12em;
      text-transform: uppercase;
      color: var(--muted);
      font-weight: 650;
    }

    .field-input,
    .field-textarea {
      width: 100%;
      border-radius: 16px;
      border: 1px solid rgba(30, 25, 22, 0.12);
      background: rgba(255, 255, 255, 0.82);
      color: var(--ink);
      font: inherit;
      padding: 12px 14px;
      outline: none;
      transition: border-color 140ms ease, box-shadow 140ms ease, background 140ms ease;
    }

    .field-input:focus,
    .field-textarea:focus {
      border-color: rgba(22, 93, 99, 0.28);
      box-shadow: 0 0 0 4px rgba(22, 93, 99, 0.12);
      background: rgba(255, 255, 255, 0.96);
    }

    .field-textarea {
      min-height: 132px;
      resize: vertical;
      font-family: "SF Mono", "Menlo", monospace;
      font-size: 0.9rem;
      line-height: 1.5;
    }

    .field-help {
      color: var(--muted);
      font-size: 0.92rem;
      line-height: 1.5;
    }

    .form-actions {
      display: flex;
      justify-content: flex-end;
      gap: 10px;
      flex-wrap: wrap;
    }

    @keyframes rise-in {
      from {
        opacity: 0;
        transform: translateY(16px);
      }
      to {
        opacity: 1;
        transform: translateY(0);
      }
    }

    @keyframes pulse {
      0%,
      100% {
        transform: scale(1);
      }
      50% {
        transform: scale(1.15);
      }
    }

    @media (max-width: 1080px) {
      .masthead-grid,
      .dashboard-grid,
      .config-grid {
        grid-template-columns: 1fr;
      }
    }

    @media (max-width: 840px) {
      .slot-actions {
        grid-template-columns: 1fr;
      }

      .slot-kpis {
        grid-template-columns: 1fr;
      }
    }

    @media (max-width: 720px) {
      main {
        width: min(100vw - 18px, 1240px);
        padding-top: 18px;
      }

      .masthead,
      .current-panel,
      .side-panel,
      .config-panel,
      .slots-panel,
      .topbar {
        padding: 18px;
      }

      .details-summary {
        padding: 16px 18px;
      }

      .details-body {
        padding: 0 18px 18px;
      }

      .panel,
      .slot-card,
      .identity-shell {
        border-radius: 22px;
      }

      .identity-shell {
        grid-template-columns: 1fr;
      }

      .config-hero {
        grid-template-columns: 1fr;
      }

      .identity-avatar {
        width: 62px;
        height: 62px;
        border-radius: 20px;
      }

      .hero-stats {
        grid-template-columns: 1fr;
      }
    }
  </style>
</head>
<body>
  <main>
    <section class="panel topbar">
      <div class="section-head">
        <div class="section-copy topbar-copy">
          <div class="eyebrow">Agent Account Hub</div>
          <h2>当前账号与已保存账号</h2>
          <p>同一个界面里管理 Codex 的 <code>~/.codex/auth.json</code>，也管理 Claude Code 的 Keychain 凭据快照。</p>
        </div>
        <div class="topbar-actions">
          <div class="provider-tabs" id="provider-tabs">
            <button class="provider-tab active" type="button" data-provider="codex">Codex</button>
            <button class="provider-tab" type="button" data-provider="claude-code">Claude Code</button>
          </div>
          <div id="sync-pill" class="sync-pill">正在读取状态</div>
          <button id="save-new-button" class="button primary" type="button">保存当前为新账号</button>
          <button id="refresh-usage-button" class="button secondary" type="button" hidden>刷新全部用量</button>
          <button id="refresh-button" class="button secondary" type="button">刷新状态</button>
        </div>
      </div>
    </section>

    <article class="panel current-panel">
      <div class="section-head">
        <div class="section-copy">
          <div class="eyebrow">Active Identity</div>
          <h2>当前活动认证</h2>
          <p>主状态按当前 provider 的 access token 判断；展开详情时再看更细的 token 与同步状态。</p>
        </div>
      </div>

      <div id="current-summary" class="identity-shell"></div>
      <div id="current-details" class="detail-grid"></div>
      <div id="current-usage-visuals" class="usage-visuals" hidden></div>
      <details class="details-shell">
        <summary class="details-summary">
          <div class="details-title">
            <span>认证详细状态</span>
          </div>
          <div id="current-auth-summary" class="summary-row"></div>
        </summary>
        <div class="details-body">
          <div id="current-auth-details" class="detail-grid"></div>
        </div>
      </details>
    </article>

    <section class="panel slots-panel">
      <div class="section-head">
        <div class="section-copy">
          <div class="eyebrow">Accounts</div>
          <h2>已保存账号</h2>
          <p>卡片只负责切换和快速操作；认证、用量和菜单栏展示配置统一放到下面的配置中心里维护。</p>
        </div>
        <div id="slot-summary" class="summary-row"></div>
      </div>

      <div id="slots" class="slots"></div>
    </section>

    <section class="panel config-panel">
      <div class="section-head">
        <div class="section-copy">
          <div class="eyebrow">Configuration Center</div>
          <h2>账号配置与菜单栏展示</h2>
          <p>这里配置的是“已保存账号记录”，不会切换当前登录。你可以直接指定想编辑的账号，再分别查看 Claude Code、claude.ai 与用量状态。</p>
        </div>
        <div id="config-summary" class="summary-row"></div>
      </div>

      <div id="config-selector" class="config-selector"></div>

      <div class="config-grid">
        <section id="selected-slot-config" class="config-card empty"></section>
        <section id="menu-bar-config" class="config-card empty"></section>
      </div>
    </section>

    <section class="panel details-panel">
      <details class="details-shell">
        <summary class="details-summary">
          <div class="details-title">
            <span>工作区路径与说明</span>
            <span class="chip muted">可选</span>
          </div>
          <span class="chip muted">展开</span>
        </summary>
        <div class="details-body">
          <div id="workspace" class="path-stack"></div>

          <div class="guide-list">
            <div class="guide-card">
              <div class="guide-step">Step 1</div>
              <div class="guide-title">保存当前凭据</div>
              <div class="guide-copy">把当前活动凭据保存成一条新的本地账号记录，之后就能直接切换回来。</div>
            </div>
            <div class="guide-card">
              <div class="guide-step">Step 2</div>
              <div class="guide-title">按账号切换</div>
              <div class="guide-copy">切换时只更新当前 provider 真正使用的凭据载体，不会重写你的 config、session 或日志目录。</div>
            </div>
            <div class="guide-card">
              <div class="guide-step">Step 3</div>
              <div class="guide-title">同账号自动去重</div>
              <div class="guide-copy">如果同一账号被再次保存，旧记录会自动合并，避免本地列表出现重复账号。</div>
            </div>
          </div>
        </div>
      </details>
    </section>

    <div id="status" class="status" aria-live="polite"></div>
  </main>

  <div id="usage-auth-modal" class="modal-backdrop" hidden>
    <div class="modal-card" role="dialog" aria-modal="true" aria-labelledby="usage-auth-heading">
      <div class="modal-head">
        <div class="eyebrow">Claude Usage Auth</div>
        <h2 id="usage-auth-heading">配置 claude.ai 认证</h2>
        <p class="modal-copy">这里配置的是这个账号查询 <code>claude.ai</code> 用量所需的认证信息，不是用量结果本身。保存后应用会刷新并展示 5 小时和 7 天的百分比，以及各自的重置时间。</p>
        <div class="chip-row">
          <span class="chip accent" id="usage-auth-title">—</span>
          <span class="chip muted">支持粘贴 sessionKey / Cookie / Request headers / usage URL</span>
        </div>
      </div>

      <form id="usage-auth-form" class="form-grid">
        <input id="usage-auth-slot-id" type="hidden" value="">

        <label class="field">
          <span class="field-label">claude.ai Session</span>
          <textarea id="usage-auth-session-input" class="field-textarea" placeholder="粘贴原始 sessionKey，或者整段 Cookie / Request headers"></textarea>
          <span id="usage-auth-session-note" class="field-help"></span>
        </label>

        <label class="field">
          <span class="field-label">Organization</span>
          <input id="usage-auth-organization-input" class="field-input" type="text" placeholder="输入 organizationId，或粘贴 usage 请求 URL">
          <span id="usage-auth-organization-note" class="field-help"></span>
        </label>

        <label class="field">
          <span class="field-label">Organization Name</span>
          <input id="usage-auth-organization-name" class="field-input" type="text" placeholder="可选，给这个 organization 起个易识别的名称">
          <span class="field-help">这个名称只用于你自己的账号列表展示，方便区分多个 Claude 订阅或组织。</span>
        </label>

        <div class="form-actions">
          <button id="usage-auth-cancel-button" class="button secondary" type="button">取消</button>
          <button id="usage-auth-save-button" class="button primary" type="submit">保存并刷新用量</button>
        </div>
      </form>
    </div>
  </div>

  <script>
    const REFRESH_INTERVAL_MS = 20000;
    const USAGE_AUTO_REFRESH_MS = 5 * 60 * 1000;
    const PROVIDERS = {
      codex: { label: "Codex" },
      "claude-code": { label: "Claude Code" }
    };
    const PROVIDER_STORAGE_KEY = "account-hub:selected-provider";
    let selectedProvider = normalizeProvider(window.localStorage.getItem(PROVIDER_STORAGE_KEY) || "codex");
    let refreshPromise = null;
    let usageRefreshPromise = null;
    let latestState = null;
    let lastUsageAutoRefreshAt = 0;
    const selectedSlotIds = {
      codex: null,
      "claude-code": null
    };

    function normalizeProvider(value) {
      return value === "claude-code" ? "claude-code" : "codex";
    }

    function providerMeta() {
      return PROVIDERS[selectedProvider] || PROVIDERS.codex;
    }

    function providerStatePath() {
      return "/api/providers/" + encodeURIComponent(selectedProvider) + "/state";
    }

    function providerActionPath(suffix) {
      return "/api/providers/" + encodeURIComponent(selectedProvider) + suffix;
    }

    function providerSupportsUsage(state = latestState) {
      return Boolean(state && state.capabilities && state.capabilities.usage_tracking);
    }

    function usageAuthMode(state = latestState) {
      return (state && state.capabilities && state.capabilities.usage_auth_mode) || "manual";
    }

    function usageSupportsManualAuthConfig(state = latestState) {
      return usageAuthMode(state) === "manual";
    }

    function providerUsageAutoRefreshMs(state = latestState) {
      const seconds = Number(state && state.capabilities && state.capabilities.usage_auto_refresh_seconds);
      if (!Number.isFinite(seconds) || seconds <= 0) {
        return USAGE_AUTO_REFRESH_MS;
      }
      return seconds * 1000;
    }

    function providerUsesIdToken() {
      return selectedProvider === "codex";
    }

    function selectedSlotId() {
      return selectedSlotIds[selectedProvider] || null;
    }

    function setSelectedSlotId(slotId) {
      selectedSlotIds[selectedProvider] = slotId || null;
    }

    function hasConfiguredUsageAccounts(state = latestState) {
      if (!providerSupportsUsage(state)) {
        return false;
      }
      return savedAccounts(state).some((slot) => Boolean((slot.usage_auth || {}).configured));
    }

    function setProviderTabs() {
      document.querySelectorAll("#provider-tabs [data-provider]").forEach((button) => {
        button.classList.toggle("active", button.dataset.provider === selectedProvider);
      });
    }

    async function request(path, options = {}) {
      const response = await fetch(path, {
        headers: { "Content-Type": "application/json" },
        cache: "no-store",
        ...options
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) {
        throw new Error(data.error || "请求失败");
      }
      return data;
    }

    function escapeHtml(value) {
      return String(value)
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#39;");
    }

    function plain(value, fallback = "—") {
      if (value === null || value === undefined || value === "") {
        return fallback;
      }
      return String(value);
    }

    function text(value, fallback = "—") {
      return escapeHtml(plain(value, fallback));
    }

    function formatDate(value) {
      if (!value) {
        return "—";
      }
      const parsed = new Date(value);
      if (Number.isNaN(parsed.getTime())) {
        return String(value);
      }
      return parsed.toLocaleString("zh-CN", {
        month: "2-digit",
        day: "2-digit",
        hour: "2-digit",
        minute: "2-digit",
        hour12: false
      });
    }

    function formatPercent(value) {
      if (value === null || value === undefined || value === "") {
        return "—";
      }
      const numeric = Number(value);
      if (!Number.isFinite(numeric)) {
        return String(value);
      }
      const rounded = Math.round(numeric * 10) / 10;
      const precision = Math.abs(rounded % 1) < 0.001 ? 0 : 1;
      return rounded.toFixed(precision) + "%";
    }

    function encodeSlotId(slotId) {
      return encodeURIComponent(String(slotId || ""));
    }

    function savedAccounts(state) {
      if (Array.isArray(state.accounts)) {
        return state.accounts;
      }
      if (Array.isArray(state.slots)) {
        return state.slots;
      }
      return [];
    }

    function selectedSlot(state = latestState) {
      const accounts = savedAccounts(state);
      if (!accounts.length) {
        setSelectedSlotId(null);
        return null;
      }
      const preferredId = selectedSlotId();
      const match = accounts.find((slot) => slot.id === preferredId) || accounts[0];
      setSelectedSlotId(match ? match.id : null);
      return match || null;
    }

    function isEditingForm() {
      const active = document.activeElement;
      if (!active) {
        return false;
      }
      const tag = String(active.tagName || "").toLowerCase();
      return tag === "input" || tag === "textarea" || active.isContentEditable;
    }

    function slotToken(slot, index) {
      const match = String(slot.id || "").match(/(\\d+)$/);
      return match ? match[1] : String(index + 1);
    }

    function identityLabel(summary, fallback = "未命名身份") {
      return (
        summary.name ||
        summary.email ||
        summary.account_id ||
        (summary.exists ? "已保存认证" : fallback)
      );
    }

    function identitySubline(summary) {
      const values = [summary.email, summary.account_id].filter(Boolean);
      if (values.length) {
        return values.join(" · ");
      }
      if (summary.exists) {
        return "已检测到有效认证文件";
      }
      return "尚未检测到活动认证";
    }

    function avatarText(summary) {
      const source = identityLabel(summary, "未");
      return source.trim().slice(0, 1).toUpperCase() || "未";
    }

    function parseDate(value) {
      if (!value) {
        return null;
      }
      const parsed = new Date(value);
      if (Number.isNaN(parsed.getTime())) {
        return null;
      }
      return parsed;
    }

    function isExpiredAt(value) {
      const parsed = parseDate(value);
      return parsed ? parsed.getTime() <= Date.now() : false;
    }

    function isExpired(summary, field = "expires_at") {
      return isExpiredAt(summary[field]);
    }

    function tokenStatusMeta(summary, tokenKind) {
      if (tokenKind === "refresh") {
        if (summary.has_refresh_token) {
          return {
            label: "Refresh Token",
            state: "已保存",
            tone: "accent",
            value: "已检测到",
            note: "当前认证里包含 refresh_token"
          };
        }
        return {
          label: "Refresh Token",
          state: "缺失",
          tone: "bad",
          value: "未检测到",
          note: "当前认证里没有 refresh_token"
        };
      }

      const isAccess = tokenKind === "access";
      const exists = isAccess ? summary.has_access_token : summary.has_id_token;
      const expiresAt = isAccess ? (summary.access_expires_at || summary.expires_at) : summary.id_expires_at;
      const label = isAccess ? "Access Token" : "ID Token";

      if (!exists) {
        return {
          label,
          state: "缺失",
          tone: "bad",
          value: "未检测到",
          note: "当前认证里没有这个 token"
        };
      }

      if (!expiresAt) {
        return {
          label,
          state: "已检测到",
          tone: "muted",
          value: "未解析到过期时间",
          note: "token 存在，但没有可读的 exp"
        };
      }

      if (isExpiredAt(expiresAt)) {
        return {
          label,
          state: "已过期",
          tone: "bad",
          value: formatDate(expiresAt),
          note: "过期时间"
        };
      }

      return {
        label,
        state: "有效",
        tone: "good",
        value: formatDate(expiresAt),
        note: "过期时间"
      };
    }

    function tokenStatusChip(summary, tokenKind) {
      const meta = tokenStatusMeta(summary, tokenKind);
      return chip(meta.label + " " + meta.state, meta.tone);
    }

    function tokenSummaryText(summary) {
      const access = tokenStatusMeta(summary, "access").state;
      const refresh = tokenStatusMeta(summary, "refresh").state;
      if (!providerUsesIdToken()) {
        return "Access " + access + " · Refresh " + refresh;
      }
      const id = tokenStatusMeta(summary, "id").state;
      return "Access " + access + " · ID " + id + " · Refresh " + refresh;
    }

    function snapshotSyncMeta(current) {
      const accountId = current.snapshot_sync_account_id || current.matched_account_id || current.matched_slot_id;
      const accountLabel = current.matched_account_label || accountId || "这条账号";
      switch (current.snapshot_sync_status) {
        case "updated":
          return {
            label: "快照已自动同步",
            tone: "good",
            detail: accountLabel + " 已更新到当前认证",
          };
        case "up_to_date":
          return {
            label: "快照已是最新",
            tone: "accent",
            detail: accountLabel + " 与当前认证完全一致",
          };
        case "not_saved":
          return {
            label: "还未关联快照",
            tone: "muted",
            detail: "当前认证还没有对应的已保存账号",
          };
        case "missing":
          return {
            label: "未检测到认证文件",
            tone: "warn",
            detail: "当前没有可同步的活动认证",
          };
        case "invalid":
          return {
            label: "认证文件异常",
            tone: "bad",
            detail: "当前认证无法解析，未做自动同步",
          };
        case "unidentifiable":
          return {
            label: "无法识别账号身份",
            tone: "warn",
            detail: "当前认证缺少可稳定识别的账号信息",
          };
        default:
          return {
            label: "快照同步状态未知",
            tone: "muted",
            detail: "当前没有可展示的同步结果",
          };
      }
    }

    function snapshotSyncChip(current) {
      const meta = snapshotSyncMeta(current);
      return chip(meta.label, meta.tone);
    }

    function statusDetailCard(meta) {
      return `
        <div class="detail-card">
          <div class="detail-label">${escapeHtml(meta.label)}</div>
          <div class="chip-row">${chip(meta.state, meta.tone)}</div>
          <div class="detail-value">${text(meta.value)}</div>
          <div class="detail-note">${text(meta.note)}</div>
        </div>
      `;
    }

    function renderAuthDetailCards(summary) {
      const kinds = providerUsesIdToken()
        ? ["access", "id", "refresh"]
        : ["access", "refresh"];
      return kinds.map((kind) => statusDetailCard(tokenStatusMeta(summary, kind))).join("");
    }

    function currentStateChip(current) {
      if (!current.exists) {
        return chip("未检测到当前凭据", "warn");
      }
      if (current.status === "invalid") {
        return chip("当前凭据异常", "bad");
      }
      return chip("当前凭据已就绪", "accent");
    }

    function matchedAccountId(current) {
      return current.matched_account_id || current.matched_slot_id || null;
    }

    function slotStateChip(slot) {
      if (!slot.snapshot.exists) {
        return chip("未保存", "warn");
      }
      if (slot.active) {
        return chip("当前认证", "good");
      }
      return chip("已保存快照", "accent");
    }

    function usageRetryDetail(usage = {}) {
      if (!usage.next_refresh_at) {
        return "";
      }
      return "；下次最早尝试 " + formatDate(usage.next_refresh_at);
    }

    function usageStatusMeta(usage = {}, usageAuth = {}) {
      if (!providerSupportsUsage()) {
        return {
          label: "当前 provider 不支持用量跟踪",
          tone: "muted",
          detail: "—"
        };
      }
      if (!usageAuth.configured) {
        if (usageSupportsManualAuthConfig()) {
          return {
            label: "未配置用量",
            tone: "muted",
            detail: "还没有保存 claude.ai 的 sessionKey 和 organizationId"
          };
        }
        return {
          label: "缺少 access token",
          tone: "warn",
          detail: usage.error || usageAuth.error || "当前保存快照缺少可用于查询 Codex 用量的 access token"
        };
      }
      if (usage.status === "auth_missing") {
        if (usageSupportsManualAuthConfig()) {
          return {
            label: "缺少 sessionKey",
            tone: "warn",
            detail: usage.error || "当前只保存了 organizationId，缺少可请求 claude.ai 的 sessionKey"
          };
        }
        return {
          label: "缺少 access token",
          tone: "warn",
          detail: (usage.error || "当前保存快照缺少 access token") + usageRetryDetail(usage)
        };
      }
      if (usage.status === "unauthorized") {
        return {
          label: "认证失效",
          tone: "bad",
          detail: usage.error
            || (usageSupportsManualAuthConfig()
              ? "claude.ai session 已失效，或没有这个 organization 的权限"
              : "Codex access token 已失效，需要重新登录并覆盖保存账号")
        };
      }
      if (usage.status === "rate_limited") {
        return {
          label: "请求受限",
          tone: "warn",
          detail: (usage.error || "用量接口暂时限制请求频率") + usageRetryDetail(usage)
        };
      }
      if (usage.status === "stale") {
        return {
          label: "缓存已过期",
          tone: "warn",
          detail: (usage.error
            || (usageSupportsManualAuthConfig()
              ? "最近一次刷新失败，当前显示的是上次成功获取的缓存"
              : "最近一次刷新失败，当前显示的是上次成功获取的 Codex 缓存")) + usageRetryDetail(usage)
        };
      }
      if (usage.status === "error") {
        return {
          label: "刷新失败",
          tone: "bad",
          detail: (usage.error
            || (usageSupportsManualAuthConfig() ? "claude.ai usage 请求失败" : "Codex usage 请求失败")) + usageRetryDetail(usage)
        };
      }
      if (usage.status === "ok") {
        return {
          label: "用量已同步",
          tone: "good",
          detail: usageSupportsManualAuthConfig() ? "最近一次用量刷新成功" : "最近一次 Codex 用量刷新成功"
        };
      }
      if (usage.status === "not_configured") {
        return {
          label: "未配置用量",
          tone: "muted",
          detail: usageSupportsManualAuthConfig()
            ? "请先为这个账号保存 claude.ai 的 sessionKey 和 organizationId"
            : "这个账号还没有可用的 Codex 用量缓存"
        };
      }
      return {
        label: "待刷新",
        tone: "muted",
        detail: usageSupportsManualAuthConfig()
          ? "已保存用量认证，但还没有成功刷新过"
          : "当前账号可以直接查询 Codex 用量，但还没有成功刷新过"
      };
    }

    function usageMetricTone(value) {
      if (value === null || value === undefined || value === "") {
        return "muted";
      }
      const numeric = Number(value);
      if (!Number.isFinite(numeric)) {
        return "muted";
      }
      if (numeric >= 80) {
        return "bad";
      }
      if (numeric >= 60) {
        return "warn";
      }
      return "good";
    }

    function usageMetricChip(label, value) {
      if (value === null || value === undefined || value === "") {
        return chip(label + " —", "muted");
      }
      return chip(label + " " + formatPercent(value), usageMetricTone(value));
    }

    function usageBar(label, value, resetAt) {
      const tone = usageMetricTone(value);
      const width = value === null || value === undefined || value === ""
        ? "6%"
        : Math.max(6, Math.min(100, Number(value))) + "%";
      return `
        <div class="usage-bar">
          <div class="usage-bar-meta">
            <div>
              <div class="usage-bar-label">${escapeHtml(label)}</div>
              <div class="usage-bar-value">${text(formatPercent(value), "—")}</div>
            </div>
            <div class="usage-bar-note">重置 ${text(formatDate(resetAt))}</div>
          </div>
          <div class="usage-track">
            <div class="usage-fill ${tone}" style="--percent:${escapeHtml(width)}"></div>
          </div>
        </div>
      `;
    }

    function usageVisuals(slotOrCurrent) {
      if (!providerSupportsUsage()) {
        return "";
      }
      const usage = (slotOrCurrent && slotOrCurrent.usage) || {};
      return `
        <div class="usage-visuals">
          ${usageBar("5h", usage.five_hour_percent, usage.five_hour_reset_at)}
          ${usageBar("7d", usage.seven_day_percent, usage.seven_day_reset_at)}
        </div>
      `;
    }

    function usageSummaryText(usage = {}, usageAuth = {}) {
      const metrics = [];
      if (usage.five_hour_percent !== null && usage.five_hour_percent !== undefined) {
        metrics.push("5h 已用 " + formatPercent(usage.five_hour_percent));
      }
      if (usage.seven_day_percent !== null && usage.seven_day_percent !== undefined) {
        metrics.push("7d 已用 " + formatPercent(usage.seven_day_percent));
      }
      if (metrics.length) {
        return metrics.join(" · ");
      }
      return usageStatusMeta(usage, usageAuth).label;
    }

    function usageResetSummary(usage = {}) {
      const parts = [];
      if (usage.five_hour_reset_at) {
        parts.push("5h 重置 " + formatDate(usage.five_hour_reset_at));
      }
      if (usage.seven_day_reset_at) {
        parts.push("7d 重置 " + formatDate(usage.seven_day_reset_at));
      }
      return parts.join(" · ") || "—";
    }

    function autoUsageRefreshLabel(state = latestState) {
      const minutes = Math.round(providerUsageAutoRefreshMs(state) / 60000);
      return "用量每 " + minutes + " 分钟自动刷新";
    }

    function chip(label, tone = "muted") {
      return '<span class="chip ' + tone + '">' + escapeHtml(label) + "</span>";
    }

    function accountDisplayTitle(account) {
      const info = account.snapshot || {};
      return account.label || info.email || info.name || info.account_id || "未命名账号";
    }

    function accountDisplayMeta(account) {
      const info = account.snapshot || {};
      const title = accountDisplayTitle(account);
      const parts = [];
      for (const value of [info.email, info.name, info.account_id]) {
        if (value && value !== title && !parts.includes(value)) {
          parts.push(value);
        }
      }
      return parts.join(" · ") || account.id || "本地保存账号";
    }

    function accountIdentityLine(account) {
      const info = account.snapshot || {};
      const title = accountDisplayTitle(account);
      const parts = [];
      for (const value of [info.name, info.email, info.account_id]) {
        if (value && value !== title && !parts.includes(value)) {
          parts.push(value);
        }
      }
      return parts.join(" · ") || "本地已保存认证";
    }

    function detailCard(label, value) {
      return `
        <div class="detail-card">
          <div class="detail-label">${escapeHtml(label)}</div>
          <div class="detail-value">${text(value)}</div>
        </div>
      `;
    }

    function pathCard(label, value, caption) {
      return `
        <div class="path-card">
          <div class="path-label">${escapeHtml(label)}</div>
          <div class="path-value">${text(value)}</div>
          <div class="guide-copy">${text(caption)}</div>
        </div>
      `;
    }

    function slotKpi(label, value) {
      return `
        <div class="slot-kpi">
          <div class="slot-kpi-label">${escapeHtml(label)}</div>
          <div class="slot-kpi-value">${text(value)}</div>
        </div>
      `;
    }

    function factRow(label, value) {
      return `
        <div class="fact-row">
          <div class="fact-label">${escapeHtml(label)}</div>
          <div class="fact-value">${text(value)}</div>
        </div>
      `;
    }

    function encodedDataValue(value) {
      return encodeURIComponent(String(value || ""));
    }

    function slotCaption(slot) {
      if (!slot.snapshot.exists) {
        return "这里还没有保存任何认证快照。";
      }
      if (slot.active) {
        return "当前活动认证与这条已保存账号记录完全一致。";
      }
      if (isExpired(slot.snapshot, "access_expires_at") || isExpired(slot.snapshot)) {
        return "快照已保存，但 Access Token 可能已过期。";
      }
      if (!slot.snapshot.has_access_token && slot.snapshot.has_refresh_token) {
        return "快照里只检测到 Refresh Token，后续是否可恢复取决于客户端刷新。";
      }
      return "可以一键把这份快照写回活动认证文件。";
    }

    function usageDetails(slot) {
      if (!providerSupportsUsage()) {
        return "";
      }
      const usage = slot.usage || {};
      const usageAuth = slot.usage_auth || {};
      const status = usageStatusMeta(usage, usageAuth);
      const orgDisplay = usageAuth.organization_name || usageAuth.organization_id || "未配置";
      return `
        <details class="token-details">
          <summary class="token-summary">
            <span>查看用量状态</span>
            <span class="token-summary-note">${text(usageSummaryText(usage, usageAuth))}</span>
          </summary>
          <div class="token-body">
            <div class="chip-row">
              ${chip(status.label, status.tone)}
              ${usageMetricChip("5h", usage.five_hour_percent)}
              ${usageMetricChip("7d", usage.seven_day_percent)}
            </div>
            <div class="slot-facts">
              ${factRow("组织", orgDisplay)}
              ${factRow("状态", status.detail)}
              ${factRow("5h 重置", formatDate(usage.five_hour_reset_at))}
              ${factRow("7d 重置", formatDate(usage.seven_day_reset_at))}
              ${factRow("刷新时间", formatDate(usage.last_success_at || usage.last_attempt_at))}
              ${factRow("自动刷新", autoUsageRefreshLabel())}
            </div>
          </div>
        </details>
      `;
    }

    function renderCurrent(current) {
      const matchedId = matchedAccountId(current);
      const matchedChip = matchedId
        ? chip("已在列表中", "accent")
        : chip("未保存到列表", "muted");
      const planChip = current.plan_type ? chip(current.plan_type, "ember") : "";
      const accessChip = tokenStatusChip(current, "access");
      const refreshChip = tokenStatusChip(current, "refresh");
      const syncChip = snapshotSyncChip(current);
      const syncMeta = snapshotSyncMeta(current);

      document.getElementById("current-summary").innerHTML = `
        <div class="identity-avatar">${escapeHtml(avatarText(current))}</div>
        <div class="identity-copy">
          <div class="identity-overline">Active Auth File</div>
          <div class="identity-title">${text(identityLabel(current, "未检测到活动认证"))}</div>
          <div class="identity-subtitle">${text(identitySubline(current))}</div>
          <div class="chip-row">
            ${currentStateChip(current)}
            ${matchedChip}
            ${planChip}
            ${syncChip}
            ${accessChip}
            ${refreshChip}
          </div>
        </div>
      `;

      const detailItems = [
        detailCard("姓名", current.name),
        detailCard("邮箱", current.email),
        detailCard("账号 ID", current.account_id),
        detailCard("认证方式", current.auth_mode),
        detailCard("已保存账号", current.matched_account_label || matchedId || "未保存"),
        detailCard("快照同步", syncMeta.detail),
        detailCard("最后刷新", formatDate(current.last_refresh)),
        detailCard("Access 到期", formatDate(current.access_expires_at || current.expires_at))
      ];
      if (providerSupportsUsage()) {
        detailItems.push(
          detailCard("当前用量", usageSummaryText(current.usage || {}, current.usage_auth || {})),
          detailCard("用量状态", usageStatusMeta(current.usage || {}, current.usage_auth || {}).detail),
          detailCard("5h 重置", formatDate((current.usage || {}).five_hour_reset_at)),
          detailCard("7d 重置", formatDate((current.usage || {}).seven_day_reset_at))
        );
      }

      document.getElementById("current-details").innerHTML = detailItems.join("");
      const currentUsageVisuals = document.getElementById("current-usage-visuals");
      if (providerSupportsUsage()) {
        currentUsageVisuals.hidden = false;
        currentUsageVisuals.innerHTML = usageVisuals(current);
      } else {
        currentUsageVisuals.hidden = true;
        currentUsageVisuals.innerHTML = "";
      }

      document.getElementById("current-auth-summary").innerHTML = [
        tokenStatusChip(current, "access"),
        providerUsesIdToken() ? tokenStatusChip(current, "id") : "",
        tokenStatusChip(current, "refresh")
      ]
        .filter(Boolean)
        .join("");

      document.getElementById("current-auth-details").innerHTML = renderAuthDetailCards(current);
    }

    function renderWorkspace(state) {
      document.getElementById("workspace").innerHTML = [
        pathCard("当前活动凭据", state.active_auth_path, "执行切换时真正会被更新的当前 provider 凭据载体"),
        pathCard("Hub 数据目录", state.data_root, "各个已保存账号的凭据快照都存在这里"),
        pathCard("项目目录", state.project_root, "源码模式下当前运行的项目根目录")
      ].join("");
    }

    function renderSlotSummary(state) {
      const accounts = savedAccounts(state);
      const savedSlots = accounts.filter((slot) => slot.snapshot && slot.snapshot.exists).length;
      const activeCount = accounts.filter((slot) => slot.active).length;
      const items = [
        chip(savedSlots + " 个已保存账号", savedSlots ? "good" : "warn"),
        chip(activeCount ? "当前账号已保存" : "当前账号未保存", activeCount ? "accent" : "muted")
      ];
      if (providerSupportsUsage(state)) {
        const configuredCount = accounts.filter((slot) => slot.usage_auth && slot.usage_auth.configured).length;
        const selectedCount = accounts.filter((slot) => slot.usage_menu_bar_visible).length;
        items.push(chip(configuredCount + " 个账号已配置用量", configuredCount ? "accent" : "muted"));
        items.push(chip(selectedCount + " 个账号显示在菜单栏", selectedCount ? "good" : "muted"));
        items.push(chip(autoUsageRefreshLabel(), "muted"));
      }
      document.getElementById("slot-summary").innerHTML = items.join("");
    }

    function renderConfigSummary(state) {
      const accounts = savedAccounts(state);
      const slot = selectedSlot(state);
      const items = [];
      if (slot) {
        items.push(chip("当前配置: " + accountDisplayTitle(slot), "accent"));
      } else {
        items.push(chip("还没有可配置账号", "muted"));
      }
      if (providerSupportsUsage(state)) {
        const selectedCount = accounts.filter((account) => account.usage_menu_bar_visible).length;
        const eligibleCount = accounts.filter((account) => account.usage_menu_bar_eligible).length;
        items.push(chip(selectedCount + " 个菜单栏展示账号", selectedCount ? "good" : "muted"));
        items.push(chip(eligibleCount + " 个有效候选账号", eligibleCount ? "accent" : "muted"));
      }
      document.getElementById("config-summary").innerHTML = items.join("");
    }

    function renderConfigSelector(state) {
      const node = document.getElementById("config-selector");
      const accounts = savedAccounts(state);
      if (!accounts.length) {
        node.innerHTML = "";
        return;
      }
      const activeId = selectedSlotId();
      node.innerHTML = accounts
        .map((slot) => `
          <button
            class="selector-pill ${slot.id === activeId ? "active" : ""}"
            type="button"
            data-action="select-config-slot"
            data-slot-id="${encodeSlotId(slot.id)}">
            ${text(accountDisplayTitle(slot))}
          </button>
        `)
        .join("");
    }

    function renderSlot(slot, index) {
      const encodedSlotId = encodeSlotId(slot.id);
      const info = slot.snapshot;
      const usage = slot.usage || {};
      const classes = ["slot-card"];
      if (slot.active) {
        classes.push("active");
      }
      if (slot.id === selectedSlotId()) {
        classes.push("selected");
      }
      if (!info.exists) {
        classes.push("empty");
      }
      const planChip = info.plan_type ? chip(info.plan_type, "ember") : "";
      const accessChip = tokenStatusChip(info, "access");
      const menuBarChip = slot.usage_menu_bar_visible ? chip("菜单栏展示中", "good") : "";
      const usageChip = providerSupportsUsage()
        ? chip(usageSummaryText(usage, slot.usage_auth || {}), usageMetricTone(usage.seven_day_percent))
        : "";

      return `
        <article class="${classes.join(" ")}" style="--delay:${index * 60}ms" data-slot-select="${encodedSlotId}">
          <div class="slot-top">
            <div class="slot-mark">${escapeHtml(slotToken(slot, index))}</div>
            <div class="chip-row">
              ${slotStateChip(slot)}
              ${menuBarChip}
              ${accessChip}
              ${planChip}
              ${usageChip}
            </div>
          </div>

          <div class="slot-title-wrap">
            <h3>${text(accountDisplayTitle(slot))}</h3>
            <div class="slot-id">${text(accountDisplayMeta(slot))}</div>
          </div>

          <div class="slot-identity">${text(accountIdentityLine(slot))}</div>
          <div class="slot-caption">${text(slotCaption(slot))}</div>

          <div class="slot-kpis">
            ${slotKpi("更新时间", formatDate(slot.updated_at))}
            ${slotKpi("Access 到期", formatDate(info.access_expires_at || info.expires_at))}
            ${providerSupportsUsage() ? slotKpi("5h 已用", formatPercent(usage.five_hour_percent)) : ""}
            ${providerSupportsUsage() ? slotKpi("7d 已用", formatPercent(usage.seven_day_percent)) : ""}
          </div>

          ${providerSupportsUsage() ? usageVisuals(slot) : ""}
          <div class="slot-hint">点击卡片查看认证信息、用量状态和菜单栏展示设置。</div>

          <div class="slot-actions">
            <button class="button secondary" type="button" data-action="capture" data-slot-id="${encodedSlotId}">
              用当前覆盖
            </button>
            <button class="button primary" type="button" data-action="switch" data-slot-id="${encodedSlotId}" ${info.exists ? "" : "disabled"}>
              切换到这里
            </button>
            <button class="button ghost" type="button" data-action="clear" data-slot-id="${encodedSlotId}" ${info.exists ? "" : "disabled"}>
              删除账号
            </button>
          </div>
        </article>
      `;
    }

    function menuBarEligibilityNote(slot) {
      const usageAuth = slot.usage_auth || {};
      const usage = slot.usage || {};
      if (slot.usage_menu_bar_eligible) {
        return usageResetSummary(usage);
      }
      if (!usageAuth.configured) {
        return usageSupportsManualAuthConfig() ? "先配置 claude.ai 认证" : "先保留可用的 access token 并成功刷新一次";
      }
      if (usage.status === "unauthorized") {
        return usageSupportsManualAuthConfig() ? "claude.ai 认证已失效" : "Codex access token 已失效";
      }
      if (usage.status === "auth_missing") {
        return usageSupportsManualAuthConfig() ? "缺少 sessionKey" : "缺少 access token";
      }
      if (usage.status === "rate_limited") {
        return "当前在退避窗口内，稍后再试";
      }
      return "先成功获取一次有效用量";
    }

    function miniUsageRow(label, value) {
      return `
        <div class="mini-usage-row">
          <div class="mini-usage-meta">
            <span>${escapeHtml(label)}</span>
            <span>${text(formatPercent(value), "—")}</span>
          </div>
          <div class="usage-track">
            <div class="usage-fill ${usageMetricTone(value)}" style="--percent:${escapeHtml(
              value === null || value === undefined || value === ""
                ? "6%"
                : Math.max(6, Math.min(100, Number(value))) + "%"
            )}"></div>
          </div>
        </div>
      `;
    }

    function selectedSlotConfig(slot) {
      const info = slot.snapshot || {};
      const usage = slot.usage || {};
      const usageAuth = slot.usage_auth || {};
      const encodedSlotId = encodeSlotId(slot.id);
      const usageStatus = usageStatusMeta(usage, usageAuth);
      const providerName = providerMeta().label;
      const usageAuthSection = usageSupportsManualAuthConfig() ? `
            <section class="module-card">
              <div class="module-head">
                <div class="module-copy">
                  <div class="module-title">claude.ai 认证信息</div>
                  <div class="module-description">这里维护的是查询用量所需的 claude.ai session 和 organization，不是 Claude Code 本体凭据。</div>
                </div>
                <div class="chip-row">
                  ${usageAuth.configured ? chip("已配置", "good") : chip("未配置", "muted")}
                  ${usageAuth.has_session_key ? chip("已保存 sessionKey", "accent") : chip("缺少 sessionKey", "warn")}
                </div>
              </div>
              <div class="slot-facts">
                ${factRow("组织", usageAuth.organization_name || usageAuth.organization_id || "未配置")}
                ${factRow("sessionKey", usageAuth.has_session_key ? "已保存到 Keychain" : "未保存")}
                ${factRow("状态", usageStatus.detail)}
              </div>
              <div class="inline-form-row">
                <button
                  class="button secondary"
                  type="button"
                  data-action="configure-usage"
                  data-slot-id="${encodedSlotId}"
                  data-slot-label="${encodedDataValue(slot.label || accountDisplayTitle(slot))}"
                  data-usage-org-id="${encodedDataValue(usageAuth.organization_id || "")}"
                  data-usage-org-name="${encodedDataValue(usageAuth.organization_name || "")}"
                  data-usage-has-session-key="${usageAuth.has_session_key ? "1" : "0"}">
                  ${usageAuth.configured || usageAuth.organization_id ? "编辑 claude.ai 认证" : "配置 claude.ai 认证"}
                </button>
                <button
                  class="button ghost"
                  type="button"
                  data-action="clear-usage"
                  data-slot-id="${encodedSlotId}"
                  ${(usageAuth.organization_id || usageAuth.has_session_key) ? "" : "disabled"}>
                  清除认证
                </button>
              </div>
            </section>
      ` : `
            <section class="module-card">
              <div class="module-head">
                <div class="module-copy">
                  <div class="module-title">Codex 用量来源</div>
                  <div class="module-description">这里不需要额外配置网页认证，直接使用这条已保存账号快照里的 access token 查询 Codex 用量。</div>
                </div>
                <div class="chip-row">
                  ${usageAuth.configured ? chip("可直接查询", "good") : chip("缺少 access token", "warn")}
                </div>
              </div>
              <div class="slot-facts">
                ${factRow("来源", usageAuth.configured ? "已保存账号快照里的 access token" : "当前保存快照里没有 access token")}
                ${factRow("状态", usageStatus.detail)}
                ${factRow("最近刷新", formatDate(usage.last_success_at || usage.last_attempt_at))}
              </div>
            </section>
      `;
      return `
        <div class="config-stack">
          <div class="config-hero">
            <div class="config-avatar">${escapeHtml(avatarText(info))}</div>
            <div class="config-copy">
              <div class="eyebrow">Selected Account</div>
              <div class="config-title">${text(accountDisplayTitle(slot))}</div>
              <div class="config-subtitle">${text(accountDisplayMeta(slot))}</div>
              <div class="chip-row">
                ${chip("仅修改已保存记录", "muted")}
                ${slotStateChip(slot)}
                ${info.auth_mode ? chip(info.auth_mode, "muted") : ""}
                ${info.plan_type ? chip(info.plan_type, "ember") : ""}
                ${providerSupportsUsage() ? chip(usageStatus.label, usageStatus.tone) : ""}
              </div>
            </div>
          </div>

          <section class="module-card">
            <div class="module-head">
              <div class="module-copy">
                <div class="module-title">账号名称</div>
                <div class="module-description">这里统一维护显示名称，不再在卡片上单独放按钮。</div>
              </div>
            </div>
            <form class="inline-form" data-role="rename-form" data-slot-id="${encodedSlotId}">
              <div class="inline-form-row">
                <input
                  class="field-input"
                  type="text"
                  data-role="rename-input"
                  value="${escapeHtml(slot.label || accountDisplayTitle(slot))}"
                  placeholder="输入一个容易区分的账号名称">
                <button class="button secondary" type="submit">保存名称</button>
              </div>
            </form>
          </section>

          <section class="module-card">
            <div class="module-head">
              <div class="module-copy">
                <div class="module-title">${text(providerName)} 认证信息</div>
                <div class="module-description">这里查看当前保存快照里的 ${text(providerName)} 基础认证状态。</div>
              </div>
            </div>
            <div class="detail-grid">
              ${detailCard("邮箱", info.email)}
              ${detailCard("姓名", info.name)}
              ${detailCard("账号 ID", info.account_id)}
              ${detailCard("最后刷新", formatDate(info.last_refresh))}
            </div>
            <div class="token-grid">
              ${renderAuthDetailCards(info)}
            </div>
          </section>

          ${providerSupportsUsage() ? `
            ${usageAuthSection}

            <section class="module-card">
              <div class="module-head">
                <div class="module-copy">
                  <div class="module-title">用量状态</div>
                  <div class="module-description">这里集中看 5 小时 / 7 天已用百分比、各自重置时间和最近刷新结果。</div>
                </div>
                <div class="chip-row">
                  ${usageMetricChip("5h", usage.five_hour_percent)}
                  ${usageMetricChip("7d", usage.seven_day_percent)}
                </div>
              </div>
              ${usageVisuals(slot)}
              <div class="detail-grid">
                ${detailCard("用量摘要", usageSummaryText(usage, usageAuth))}
                ${detailCard("5h 重置", formatDate(usage.five_hour_reset_at))}
                ${detailCard("7d 重置", formatDate(usage.seven_day_reset_at))}
                ${detailCard("最近刷新", formatDate(usage.last_success_at || usage.last_attempt_at))}
              </div>
              <div class="inline-form-row">
                <button
                  class="button secondary"
                  type="button"
                  data-action="refresh-usage"
                  data-slot-id="${encodedSlotId}"
                  ${usageAuth.configured ? "" : "disabled"}>
                  刷新这个账号的用量
                </button>
              </div>
            </section>
          ` : ""}
        </div>
      `;
    }

    function menuBarSelectionRow(slot) {
      const encodedSlotId = encodeSlotId(slot.id);
      const disabled = !(slot.usage_menu_bar_visible || slot.usage_menu_bar_eligible);
      const classes = ["selection-row"];
      if (disabled) {
        classes.push("disabled");
      }
      return `
        <div class="${classes.join(" ")}">
          <div class="selection-copy">
            <div class="selection-title">${text(accountDisplayTitle(slot))}</div>
            <div class="selection-subtitle">${text(menuBarEligibilityNote(slot))}</div>
            <div class="chip-row">
              ${slot.usage_menu_bar_visible ? chip("菜单栏展示中", "good") : chip("未展示", "muted")}
              ${chip(usageSummaryText(slot.usage || {}, slot.usage_auth || {}), usageMetricTone((slot.usage || {}).seven_day_percent))}
            </div>
          </div>
          <button
            class="button secondary"
            type="button"
            data-action="toggle-menu-bar"
            data-slot-id="${encodedSlotId}"
            data-visible="${slot.usage_menu_bar_visible ? "1" : "0"}"
            ${disabled ? "disabled" : ""}>
            ${slot.usage_menu_bar_visible ? "移出菜单栏" : "加入菜单栏"}
          </button>
        </div>
      `;
    }

    function menuBarPreviewCard(slot) {
      const usage = slot.usage || {};
      return `
        <div class="module-card">
          <div class="module-head">
            <div class="module-copy">
              <div class="module-title">${text(accountDisplayTitle(slot))}</div>
              <div class="module-description">${text(usageSummaryText(usage, slot.usage_auth || {}))}</div>
            </div>
            <div class="chip-row">${chip("展示中", "good")}</div>
          </div>
          <div class="mini-usage">
            ${miniUsageRow("5h", usage.five_hour_percent)}
            ${miniUsageRow("7d", usage.seven_day_percent)}
          </div>
        </div>
      `;
    }

    function renderSelectedSlotConfig(state) {
      const node = document.getElementById("selected-slot-config");
      const slot = selectedSlot(state);
      if (!slot) {
        node.className = "config-card empty";
        node.innerHTML = `
          <div class="empty-state">
            还没有可配置的账号。先保存一个账号，或者从上面的列表里选择一条记录。
          </div>
        `;
        return;
      }
      node.className = "config-card";
      node.innerHTML = selectedSlotConfig(slot);
    }

    function renderMenuBarConfig(state) {
      const node = document.getElementById("menu-bar-config");
      if (!providerSupportsUsage(state)) {
        node.className = "config-card empty";
        node.innerHTML = `
          <div class="empty-state">
            当前 provider 暂时没有用量和菜单栏展示配置能力。切到支持用量的 provider 后，这里会显示可选账号和展示预览。
          </div>
        `;
        return;
      }

      const accounts = savedAccounts(state);
      const selectedAccounts = accounts.filter((slot) => slot.usage_menu_bar_visible);
      const eligibleAccounts = accounts.filter((slot) => slot.usage_menu_bar_eligible);
      node.className = "config-card";
      node.innerHTML = `
        <div class="module-head">
          <div class="module-copy">
            <div class="module-title">菜单栏展示</div>
            <div class="module-description">只在这里管理哪些账号进入菜单栏展示。无效账号会保留说明，但不能加入。</div>
          </div>
          <div class="chip-row">
            ${chip(selectedAccounts.length + " 个展示中", selectedAccounts.length ? "good" : "muted")}
            ${chip(eligibleAccounts.length + " 个可选账号", eligibleAccounts.length ? "accent" : "muted")}
          </div>
        </div>

        <div class="preview-stack">
          ${selectedAccounts.length
            ? selectedAccounts.map(menuBarPreviewCard).join("")
            : `<div class="empty-state">还没有账号加入菜单栏展示。先为账号配置 claude.ai 认证并成功刷新一次用量，然后再加入。</div>`}
        </div>

        <div class="selection-stack">
          ${accounts.length
            ? accounts.map(menuBarSelectionRow).join("")
            : `<div class="empty-state">当前还没有已保存账号。</div>`}
        </div>
      `;
    }

    function renderConfiguration(state) {
      renderConfigSummary(state);
      renderConfigSelector(state);
      renderSelectedSlotConfig(state);
      renderMenuBarConfig(state);
    }

    function renderSlots(state) {
      const node = document.getElementById("slots");
      const accounts = savedAccounts(state);
      if (!accounts.length) {
        node.innerHTML = `
          <article class="slot-card empty">
            <div class="slot-title-wrap">
              <h3>还没有已保存账号</h3>
              <div class="slot-id">先把当前登录保存进去，之后就可以在这里直接切换。</div>
            </div>
            <div class="slot-actions">
              <button class="button primary" type="button" data-action="create-new">保存当前为新账号</button>
            </div>
          </article>
        `;
        return;
      }
      selectedSlot(state);
      node.innerHTML = accounts.map(renderSlot).join("");
    }

    function setSyncPill(message, tone = "idle") {
      const pill = document.getElementById("sync-pill");
      pill.textContent = message;
      pill.classList.remove("syncing", "error");
      if (tone === "syncing") {
        pill.classList.add("syncing");
      }
      if (tone === "error") {
        pill.classList.add("error");
      }
    }

    function flash(message, isError = false) {
      const node = document.getElementById("status");
      node.textContent = message;
      node.classList.toggle("error", isError);
      node.classList.add("show");
      window.clearTimeout(window.__hubStatusTimer);
      window.__hubStatusTimer = window.setTimeout(() => node.classList.remove("show"), 2600);
    }

    async function refreshState(options = {}) {
      if (refreshPromise) {
        return refreshPromise;
      }
      const quiet = Boolean(options.quiet);
      setProviderTabs();
      setSyncPill("正在同步 " + providerMeta().label + " 状态", "syncing");

      refreshPromise = (async () => {
        try {
          const state = await request(providerStatePath());
          latestState = state;
          renderCurrent(state.current);
          renderWorkspace(state);
          renderSlotSummary(state);
          renderSlots(state);
          renderConfiguration(state);
          document.getElementById("refresh-usage-button").hidden = !providerSupportsUsage(state);
          setSyncPill(providerMeta().label + " 状态已同步", "idle");
          if (!options.skipUsageAutoRefresh && shouldAutoRefreshUsage(state)) {
            window.setTimeout(() => {
              refreshAllUsage({ quiet: true, auto: true }).catch(() => {});
            }, 0);
          }
          return state;
        } catch (error) {
          setSyncPill(providerMeta().label + " 读取失败", "error");
          if (!quiet) {
            flash(error.message, true);
          }
          throw error;
        } finally {
          refreshPromise = null;
        }
      })();

      return refreshPromise;
    }

    async function createNewAccountFromCurrent() {
      const data = await request(providerActionPath("/accounts/create-from-current"), {
        method: "POST",
        body: "{}"
      });
      if (data.created_new_account) {
        flash("已把当前 " + providerMeta().label + " 登录保存为新账号");
      } else {
        flash("当前登录已存在，已更新到已有账号");
      }
      await refreshState({ quiet: true });
    }

    async function captureSlot(slotId) {
      const data = await request(providerActionPath("/accounts/" + encodeSlotId(slotId) + "/capture"), {
        method: "POST",
        body: "{}"
      });
      const moved = data.cleared_account_ids || data.cleared_slot_ids || [];
      if (moved.length) {
        flash("已覆盖该账号，并移除重复记录：" + moved.join(", "));
      } else {
        flash("已用当前登录覆盖该账号");
      }
      await refreshState({ quiet: true });
    }

    async function switchSlot(slotId) {
      await request(providerActionPath("/accounts/" + encodeSlotId(slotId) + "/switch"), {
        method: "POST",
        body: "{}"
      });
      flash("已切换到所选账号");
      await refreshState({ quiet: true });
    }

    async function clearSlot(slotId) {
      const confirmed = window.confirm("确认删除这个已保存账号吗？这不会删除当前 " + providerMeta().label + " 正在使用的凭据。");
      if (!confirmed) {
        return;
      }
      await request(providerActionPath("/accounts/" + encodeSlotId(slotId) + "/delete"), {
        method: "POST",
        body: "{}"
      });
      flash("已删除该账号");
      await refreshState({ quiet: true });
    }

    async function renameSlot(slotId, nextLabel) {
      const trimmed = String(nextLabel || "").trim();
      if (!trimmed) {
        throw new Error("名称不能为空");
      }

      await request(providerActionPath("/accounts/" + encodeSlotId(slotId) + "/rename"), {
        method: "POST",
        body: JSON.stringify({ label: trimmed })
      });
      flash("已更新账号名称");
      await refreshState({ quiet: true });
    }

    function openUsageAuthModal(options) {
      const modal = document.getElementById("usage-auth-modal");
      modal.hidden = false;
      document.getElementById("usage-auth-slot-id").value = options.slotId;
      document.getElementById("usage-auth-title").textContent = options.title;
      document.getElementById("usage-auth-session-input").value = "";
      document.getElementById("usage-auth-organization-input").value = options.organizationId || "";
      document.getElementById("usage-auth-organization-name").value = options.organizationName || "";
      document.getElementById("usage-auth-session-note").textContent = options.hasSessionKey
        ? "当前已经保存过 sessionKey。你可以留空以继续沿用，也可以粘贴新的 sessionKey、整段 Cookie 或请求头来覆盖。"
        : "这里可以直接粘贴原始 sessionKey，也可以粘贴整段 Cookie / Request headers；应用会自动提取 sessionKey。";
      document.getElementById("usage-auth-organization-note").textContent =
        "这里可以输入 organizationId，也可以粘贴类似 /api/organizations/<id>/usage 的 URL。";
      document.getElementById("usage-auth-session-input").focus();
    }

    function closeUsageAuthModal() {
      const modal = document.getElementById("usage-auth-modal");
      modal.hidden = true;
      document.getElementById("usage-auth-form").reset();
    }

    async function configureUsage(slotId, options) {
      openUsageAuthModal({
        slotId,
        title: options.title,
        organizationId: options.organizationId,
        organizationName: options.organizationName,
        hasSessionKey: options.hasSessionKey
      });
    }

    async function refreshUsage(slotId) {
      await request(providerActionPath("/accounts/" + encodeSlotId(slotId) + "/usage/refresh"), {
        method: "POST",
        body: "{}"
      });
      flash("已刷新这个账号的用量");
      await refreshState({ quiet: true });
    }

    async function clearUsage(slotId) {
      const confirmed = window.confirm("确认清除这个账号保存的 claude.ai 用量认证吗？");
      if (!confirmed) {
        return;
      }
      await request(providerActionPath("/accounts/" + encodeSlotId(slotId) + "/usage-auth/clear"), {
        method: "POST",
        body: "{}"
      });
      flash("已清除这个账号的用量认证");
      await refreshState({ quiet: true });
    }

    async function toggleMenuBarUsage(slotId, visible) {
      await request(providerActionPath("/accounts/" + encodeSlotId(slotId) + "/usage-menu-bar"), {
        method: "POST",
        body: JSON.stringify({ visible })
      });
      flash(visible ? "已加入菜单栏展示" : "已从菜单栏展示移除");
      await refreshState({ quiet: true, skipUsageAutoRefresh: true });
    }

    function shouldAutoRefreshUsage(state = latestState) {
      if (!hasConfiguredUsageAccounts(state)) {
        return false;
      }
      if (usageRefreshPromise) {
        return false;
      }
      return Date.now() - lastUsageAutoRefreshAt >= providerUsageAutoRefreshMs(state);
    }

    async function refreshAllUsage(options = {}) {
      if (usageRefreshPromise) {
        return usageRefreshPromise;
      }
      const quiet = Boolean(options.quiet);
      const auto = Boolean(options.auto);
      lastUsageAutoRefreshAt = Date.now();
      usageRefreshPromise = (async () => {
        await request(providerActionPath("/usage/refresh-all"), {
          method: "POST",
          body: "{}"
        });
        if (!quiet && !auto) {
          flash("已刷新当前 provider 下已配置账号的用量");
        }
        await refreshState({ quiet: true, skipUsageAutoRefresh: true });
      })();
      try {
        return await usageRefreshPromise;
      } finally {
        usageRefreshPromise = null;
      }
    }

    document.getElementById("refresh-button").addEventListener("click", () => {
      refreshState().catch(() => {});
    });

    document.getElementById("refresh-usage-button").addEventListener("click", (event) => {
      const button = event.currentTarget;
      button.disabled = true;
      refreshAllUsage()
        .catch((error) => flash(error.message, true))
        .finally(() => {
          button.disabled = false;
        });
    });

    document.getElementById("usage-auth-cancel-button").addEventListener("click", () => {
      closeUsageAuthModal();
    });

    document.getElementById("usage-auth-modal").addEventListener("click", (event) => {
      if (event.target.id === "usage-auth-modal") {
        closeUsageAuthModal();
      }
    });

    document.getElementById("usage-auth-form").addEventListener("submit", (event) => {
      event.preventDefault();
      const submitButton = document.getElementById("usage-auth-save-button");
      const slotId = document.getElementById("usage-auth-slot-id").value;
      const sessionInput = document.getElementById("usage-auth-session-input").value;
      const organizationInput = document.getElementById("usage-auth-organization-input").value;
      const organizationName = document.getElementById("usage-auth-organization-name").value;
      submitButton.disabled = true;
      request(providerActionPath("/accounts/" + encodeSlotId(slotId) + "/usage-auth"), {
        method: "POST",
        body: JSON.stringify({
          session_input: sessionInput,
          organization_input: organizationInput,
          organization_name: organizationName
        })
      })
        .then(() => {
          closeUsageAuthModal();
          flash("已保存 claude.ai 认证，并尝试刷新当前用量");
          return refreshState({ quiet: true, skipUsageAutoRefresh: true });
        })
        .catch((error) => flash(error.message, true))
        .finally(() => {
          submitButton.disabled = false;
        });
    });

    document.getElementById("provider-tabs").addEventListener("click", (event) => {
      const button = event.target.closest("button[data-provider]");
      if (!button) {
        return;
      }
      const nextProvider = normalizeProvider(button.dataset.provider || "codex");
      if (nextProvider === selectedProvider) {
        return;
      }
      selectedProvider = nextProvider;
      window.localStorage.setItem(PROVIDER_STORAGE_KEY, selectedProvider);
      refreshState().catch(() => {});
    });

    document.getElementById("config-selector").addEventListener("click", (event) => {
      const button = event.target.closest("button[data-action='select-config-slot']");
      if (!button) {
        return;
      }
      const slotId = decodeURIComponent(button.dataset.slotId || "");
      if (!slotId || slotId === selectedSlotId()) {
        return;
      }
      setSelectedSlotId(slotId);
      renderSlots(latestState);
      renderConfiguration(latestState);
    });

    document.getElementById("save-new-button").addEventListener("click", (event) => {
      const button = event.currentTarget;
      button.disabled = true;
      createNewAccountFromCurrent()
        .catch((error) => flash(error.message, true))
        .finally(() => {
          button.disabled = false;
        });
    });

    document.getElementById("slots").addEventListener("click", (event) => {
      const button = event.target.closest("button[data-action]");
      if (!button || button.disabled) {
        const card = event.target.closest("[data-slot-select]");
        if (!card) {
          return;
        }
        const slotId = decodeURIComponent(card.dataset.slotSelect || "");
        if (!slotId || slotId === selectedSlotId()) {
          return;
        }
        setSelectedSlotId(slotId);
        renderSlots(latestState);
        renderConfiguration(latestState);
        return;
      }

      const action = button.dataset.action;
      if (action === "create-new") {
        button.disabled = true;
        createNewAccountFromCurrent()
          .catch((error) => flash(error.message, true))
          .finally(() => {
            button.disabled = false;
          });
        return;
      }

      const slotId = decodeURIComponent(button.dataset.slotId || "");
      if (!slotId) {
        return;
      }

      const runner =
        action === "capture"
          ? captureSlot
          : action === "switch"
            ? switchSlot
            : action === "clear"
              ? clearSlot
              : null;

      if (!runner) {
        return;
      }

      button.disabled = true;
      runner(slotId)
        .catch((error) => flash(error.message, true))
        .finally(() => {
          button.disabled = false;
        });
    });

    document.getElementById("selected-slot-config").addEventListener("click", (event) => {
      const button = event.target.closest("button[data-action]");
      if (!button || button.disabled) {
        return;
      }
      const slotId = decodeURIComponent(button.dataset.slotId || "");
      if (!slotId) {
        return;
      }

      const action = button.dataset.action;
      if (action === "configure-usage") {
        button.disabled = true;
        configureUsage(slotId, {
          title: decodeURIComponent(button.dataset.slotLabel || ""),
          organizationId: decodeURIComponent(button.dataset.usageOrgId || ""),
          organizationName: decodeURIComponent(button.dataset.usageOrgName || ""),
          hasSessionKey: button.dataset.usageHasSessionKey === "1"
        })
          .catch((error) => flash(error.message, true))
          .finally(() => {
            button.disabled = false;
          });
        return;
      }

      const runner =
        action === "refresh-usage"
          ? refreshUsage
          : action === "clear-usage"
            ? clearUsage
            : null;

      if (!runner) {
        return;
      }

      button.disabled = true;
      runner(slotId)
        .catch((error) => flash(error.message, true))
        .finally(() => {
          button.disabled = false;
        });
    });

    document.getElementById("selected-slot-config").addEventListener("submit", (event) => {
      const form = event.target.closest("form[data-role='rename-form']");
      if (!form) {
        return;
      }
      event.preventDefault();
      const slotId = decodeURIComponent(form.dataset.slotId || "");
      const input = form.querySelector("[data-role='rename-input']");
      const submitButton = form.querySelector("button[type='submit']");
      if (!slotId || !input || !submitButton) {
        return;
      }
      submitButton.disabled = true;
      renameSlot(slotId, input.value)
        .catch((error) => flash(error.message, true))
        .finally(() => {
          submitButton.disabled = false;
        });
    });

    document.getElementById("menu-bar-config").addEventListener("click", (event) => {
      const button = event.target.closest("button[data-action='toggle-menu-bar']");
      if (!button || button.disabled) {
        return;
      }
      const slotId = decodeURIComponent(button.dataset.slotId || "");
      if (!slotId) {
        return;
      }
      button.disabled = true;
      toggleMenuBarUsage(slotId, button.dataset.visible !== "1")
        .catch((error) => flash(error.message, true))
        .finally(() => {
          button.disabled = false;
        });
    });

    document.addEventListener("visibilitychange", () => {
      if (!document.hidden && !isEditingForm()) {
        refreshState({ quiet: true }).catch(() => {});
      }
    });

    window.setInterval(() => {
      if (!document.hidden && !isEditingForm()) {
        refreshState({ quiet: true }).catch(() => {});
      }
    }, REFRESH_INTERVAL_MS);

    refreshState().catch(() => {});
  </script>
</body>
</html>
"""


class AuthHubRequestHandler(BaseHTTPRequestHandler):
    hub: UnifiedAuthHub

    def do_GET(self) -> None:
        if self.path == "/":
            self._send_html(INDEX_HTML)
            return
        if self.path == "/api/state":
            self._send_json(self.hub.provider_overview("codex"))
            return
        provider_state_match = re.fullmatch(r"/api/providers/([^/]+)/state", self.path)
        if provider_state_match:
            try:
                provider = normalize_provider_name(provider_state_match.group(1))
                payload = self.hub.provider_overview(provider)
            except AuthHubError as exc:
                self._send_error_json(HTTPStatus.BAD_REQUEST, str(exc))
                return
            self._send_json(payload)
            return
        self._send_error_json(HTTPStatus.NOT_FOUND, "not found")

    def do_POST(self) -> None:
        if self.path == "/api/accounts/create-from-current":
            self._read_json_body()
            try:
                payload = self.hub.create_account_from_current("codex")
            except AuthHubError as exc:
                self._send_error_json(HTTPStatus.BAD_REQUEST, str(exc))
                return
            self._send_json(payload)
            return

        provider_create_match = re.fullmatch(r"/api/providers/([^/]+)/accounts/create-from-current", self.path)
        if provider_create_match:
            self._read_json_body()
            try:
                provider = normalize_provider_name(provider_create_match.group(1))
                payload = self.hub.create_account_from_current(provider)
            except AuthHubError as exc:
                self._send_error_json(HTTPStatus.BAD_REQUEST, str(exc))
                return
            self._send_json(payload)
            return

        provider_usage_auth_match = re.fullmatch(
            r"/api/providers/([^/]+)/(?:accounts|slots)/([^/]+)/usage-auth",
            self.path,
        )
        if provider_usage_auth_match:
            provider = provider_usage_auth_match.group(1)
            slot_id = provider_usage_auth_match.group(2)
            payload = self._read_json_body()
            try:
                session_key, organization_id, organization_name = self._parse_usage_auth_payload(payload)
                result = self.hub.set_usage_auth(
                    provider,
                    slot_id,
                    session_key,
                    organization_id,
                    organization_name,
                )
            except AuthHubError as exc:
                self._send_error_json(HTTPStatus.BAD_REQUEST, str(exc))
                return
            self._send_json(result)
            return

        provider_usage_clear_match = re.fullmatch(
            r"/api/providers/([^/]+)/(?:accounts|slots)/([^/]+)/usage-auth/clear",
            self.path,
        )
        if provider_usage_clear_match:
            provider = provider_usage_clear_match.group(1)
            slot_id = provider_usage_clear_match.group(2)
            self._read_json_body()
            try:
                result = self.hub.clear_usage_auth(provider, slot_id)
            except AuthHubError as exc:
                self._send_error_json(HTTPStatus.BAD_REQUEST, str(exc))
                return
            self._send_json(result)
            return

        provider_usage_refresh_match = re.fullmatch(
            r"/api/providers/([^/]+)/(?:accounts|slots)/([^/]+)/usage/refresh",
            self.path,
        )
        if provider_usage_refresh_match:
            provider = provider_usage_refresh_match.group(1)
            slot_id = provider_usage_refresh_match.group(2)
            self._read_json_body()
            try:
                result = self.hub.refresh_usage(provider, slot_id)
            except AuthHubError as exc:
                self._send_error_json(HTTPStatus.BAD_REQUEST, str(exc))
                return
            self._send_json(result)
            return

        provider_usage_refresh_all_match = re.fullmatch(
            r"/api/providers/([^/]+)/usage/refresh-all",
            self.path,
        )
        if provider_usage_refresh_all_match:
            provider = provider_usage_refresh_all_match.group(1)
            self._read_json_body()
            try:
                result = self.hub.refresh_all_usage(provider)
            except AuthHubError as exc:
                self._send_error_json(HTTPStatus.BAD_REQUEST, str(exc))
                return
            self._send_json(result)
            return

        provider_usage_menu_bar_match = re.fullmatch(
            r"/api/providers/([^/]+)/(?:accounts|slots)/([^/]+)/usage-menu-bar",
            self.path,
        )
        if provider_usage_menu_bar_match:
            provider = provider_usage_menu_bar_match.group(1)
            slot_id = provider_usage_menu_bar_match.group(2)
            payload = self._read_json_body()
            try:
                visible = self._parse_visible(payload)
                result = self.hub.set_usage_menu_bar_visible(provider, slot_id, visible)
            except AuthHubError as exc:
                self._send_error_json(HTTPStatus.BAD_REQUEST, str(exc))
                return
            self._send_json(result)
            return

        rename_match = re.fullmatch(r"/api/(?:accounts|slots)/([^/]+)/rename", self.path)
        if rename_match:
            slot_id = rename_match.group(1)
            payload = self._read_json_body()
            try:
                label = self._parse_label(payload)
                result = self.hub.rename_account("codex", slot_id, label)
            except AuthHubError as exc:
                self._send_error_json(HTTPStatus.BAD_REQUEST, str(exc))
                return
            self._send_json(result)
            return

        provider_rename_match = re.fullmatch(r"/api/providers/([^/]+)/(?:accounts|slots)/([^/]+)/rename", self.path)
        if provider_rename_match:
            provider = provider_rename_match.group(1)
            slot_id = provider_rename_match.group(2)
            payload = self._read_json_body()
            try:
                label = self._parse_label(payload)
                result = self.hub.rename_account(provider, slot_id, label)
            except AuthHubError as exc:
                self._send_error_json(HTTPStatus.BAD_REQUEST, str(exc))
                return
            self._send_json(result)
            return

        capture_match = re.fullmatch(r"/api/(?:accounts|slots)/([^/]+)/capture", self.path)
        if capture_match:
            slot_id = capture_match.group(1)
            self._read_json_body()
            try:
                payload = self.hub.save_current_to_account("codex", slot_id)
            except AuthHubError as exc:
                self._send_error_json(HTTPStatus.BAD_REQUEST, str(exc))
                return
            self._send_json(payload)
            return

        provider_capture_match = re.fullmatch(r"/api/providers/([^/]+)/(?:accounts|slots)/([^/]+)/capture", self.path)
        if provider_capture_match:
            provider = provider_capture_match.group(1)
            slot_id = provider_capture_match.group(2)
            self._read_json_body()
            try:
                payload = self.hub.save_current_to_account(provider, slot_id)
            except AuthHubError as exc:
                self._send_error_json(HTTPStatus.BAD_REQUEST, str(exc))
                return
            self._send_json(payload)
            return

        switch_match = re.fullmatch(r"/api/(?:accounts|slots)/([^/]+)/switch", self.path)
        if switch_match:
            slot_id = switch_match.group(1)
            self._read_json_body()
            try:
                payload = self.hub.switch("codex", slot_id)
            except AuthHubError as exc:
                self._send_error_json(HTTPStatus.BAD_REQUEST, str(exc))
                return
            self._send_json(payload)
            return

        provider_switch_match = re.fullmatch(r"/api/providers/([^/]+)/(?:accounts|slots)/([^/]+)/switch", self.path)
        if provider_switch_match:
            provider = provider_switch_match.group(1)
            slot_id = provider_switch_match.group(2)
            self._read_json_body()
            try:
                payload = self.hub.switch(provider, slot_id)
            except AuthHubError as exc:
                self._send_error_json(HTTPStatus.BAD_REQUEST, str(exc))
                return
            self._send_json(payload)
            return

        clear_match = re.fullmatch(r"/api/(?:accounts|slots)/([^/]+)/(?:clear|delete)", self.path)
        if clear_match:
            slot_id = clear_match.group(1)
            self._read_json_body()
            try:
                payload = self.hub.delete_account("codex", slot_id)
            except AuthHubError as exc:
                self._send_error_json(HTTPStatus.BAD_REQUEST, str(exc))
                return
            self._send_json(payload)
            return

        provider_clear_match = re.fullmatch(
            r"/api/providers/([^/]+)/(?:accounts|slots)/([^/]+)/(?:clear|delete)",
            self.path,
        )
        if provider_clear_match:
            provider = provider_clear_match.group(1)
            slot_id = provider_clear_match.group(2)
            self._read_json_body()
            try:
                payload = self.hub.delete_account(provider, slot_id)
            except AuthHubError as exc:
                self._send_error_json(HTTPStatus.BAD_REQUEST, str(exc))
                return
            self._send_json(payload)
            return

        self._send_error_json(HTTPStatus.NOT_FOUND, "not found")

    def log_message(self, format: str, *args: Any) -> None:
        return

    def _read_json_body(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0:
            return {}
        raw = self.rfile.read(length)
        if not raw:
            return {}
        try:
            payload = json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise AuthHubError(f"invalid JSON body: {exc}") from exc
        if not isinstance(payload, dict):
            raise AuthHubError("JSON body must be an object")
        return payload

    def _parse_label(self, payload: dict[str, Any]) -> str:
        label = payload.get("label")
        if not isinstance(label, str) or not label.strip():
            raise AuthHubError("label must not be empty")
        return label.strip()

    def _parse_visible(self, payload: dict[str, Any]) -> bool:
        visible = payload.get("visible")
        if isinstance(visible, bool):
            return visible
        if isinstance(visible, (int, float)):
            return bool(visible)
        if isinstance(visible, str):
            normalized = visible.strip().lower()
            if normalized in {"1", "true", "yes", "on"}:
                return True
            if normalized in {"0", "false", "no", "off"}:
                return False
        raise AuthHubError("visible must be a boolean")

    def _parse_usage_auth_payload(self, payload: dict[str, Any]) -> tuple[str, str, str | None]:
        session_key = payload.get("session_key")
        if session_key in (None, ""):
            session_key = payload.get("session_input")
        organization_id = payload.get("organization_id")
        if organization_id in (None, ""):
            organization_id = payload.get("organization_input")
        organization_name = payload.get("organization_name")
        if session_key is None:
            session_key = ""
        if not isinstance(session_key, str):
            raise AuthHubError("session_key must be a string")
        if not isinstance(organization_id, str) or not organization_id.strip():
            raise AuthHubError("organization_id 不能为空")
        if organization_name is not None and not isinstance(organization_name, str):
            raise AuthHubError("organization_name must be a string")
        normalized_name = organization_name.strip() if isinstance(organization_name, str) else None
        return (
            self._extract_session_key(session_key),
            self._extract_organization_id(organization_id),
            normalized_name or None,
        )

    def _extract_session_key(self, raw_value: str) -> str:
        candidate = raw_value.strip()
        if not candidate:
            return ""
        match = re.search(r"(?:^|[;\s])sessionKey=([^;\s]+)", candidate)
        if match:
            return match.group(1).strip().strip('"').strip("'")
        return candidate.strip().strip('"').strip("'")

    def _extract_organization_id(self, raw_value: str) -> str:
        candidate = raw_value.strip()
        if not candidate:
            raise AuthHubError("organization_id 不能为空")
        patterns = [
            r"/api/organizations/([^/?#]+)/usage",
            r"/organizations/([^/?#]+)/usage",
            r"/organizations/([^/?#]+)",
            r"organization(?:Id)?=([A-Za-z0-9._-]+)",
        ]
        for pattern in patterns:
            match = re.search(pattern, candidate)
            if match:
                return match.group(1).strip().strip('"').strip("'")
        return candidate.strip().strip('"').strip("'")

    def _send_html(self, html: str) -> None:
        encoded = html.encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def _send_json(self, payload: dict[str, Any], status: HTTPStatus = HTTPStatus.OK) -> None:
        encoded = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def _send_error_json(self, status: HTTPStatus, message: str) -> None:
        self._send_json({"error": message}, status=status)


def make_server(hub: UnifiedAuthHub, host: str = "127.0.0.1", port: int = 8766) -> ThreadingHTTPServer:
    handler = type("BoundAuthHubRequestHandler", (AuthHubRequestHandler,), {"hub": hub})
    return ThreadingHTTPServer((host, port), handler)


def serve(hub: UnifiedAuthHub, host: str = "127.0.0.1", port: int = 8766) -> None:
    server = make_server(hub, host=host, port=port)
    bound_host, bound_port = server.server_address[:2]
    print(f"Agent Account Hub running at http://{bound_host}:{bound_port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
