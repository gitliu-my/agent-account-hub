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
      grid-template-columns: repeat(4, minmax(0, 1fr));
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
      .dashboard-grid {
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
          <p>可以把当前登录保存为新账号，也可以用当前登录覆盖已有账号，然后随时切换或删除。</p>
        </div>
        <div id="slot-summary" class="summary-row"></div>
      </div>

      <div id="slots" class="slots"></div>
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

  <script>
    const REFRESH_INTERVAL_MS = 20000;
    const PROVIDERS = {
      codex: { label: "Codex" },
      "claude-code": { label: "Claude Code" }
    };
    const PROVIDER_STORAGE_KEY = "account-hub:selected-provider";
    let selectedProvider = normalizeProvider(window.localStorage.getItem(PROVIDER_STORAGE_KEY) || "codex");
    let refreshPromise = null;

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
      return "Access " + access + " · Refresh " + refresh;
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
      return [
        statusDetailCard(tokenStatusMeta(summary, "access")),
        statusDetailCard(tokenStatusMeta(summary, "id")),
        statusDetailCard(tokenStatusMeta(summary, "refresh"))
      ].join("");
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

      document.getElementById("current-details").innerHTML = [
        detailCard("姓名", current.name),
        detailCard("邮箱", current.email),
        detailCard("账号 ID", current.account_id),
        detailCard("认证方式", current.auth_mode),
        detailCard("已保存账号", current.matched_account_label || matchedId || "未保存"),
        detailCard("快照同步", syncMeta.detail),
        detailCard("最后刷新", formatDate(current.last_refresh)),
        detailCard("Access 到期", formatDate(current.access_expires_at || current.expires_at))
      ].join("");

      document.getElementById("current-auth-summary").innerHTML = [
        tokenStatusChip(current, "access"),
        tokenStatusChip(current, "id"),
        tokenStatusChip(current, "refresh")
      ].join("");

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
      document.getElementById("slot-summary").innerHTML = [
        chip(savedSlots + " 个已保存账号", savedSlots ? "good" : "warn"),
        chip(activeCount ? "当前账号已保存" : "当前账号未保存", activeCount ? "accent" : "muted")
      ].join("");
    }

    function renderSlot(slot, index) {
      const encodedSlotId = encodeSlotId(slot.id);
      const info = slot.snapshot;
      const classes = ["slot-card"];
      if (slot.active) {
        classes.push("active");
      }
      if (!info.exists) {
        classes.push("empty");
      }
      const planChip = info.plan_type ? chip(info.plan_type, "ember") : "";
      const authModeChip = info.auth_mode ? chip(info.auth_mode, "muted") : "";
      const accessChip = tokenStatusChip(info, "access");

      return `
        <article class="${classes.join(" ")}" style="--delay:${index * 60}ms">
          <div class="slot-top">
            <div class="slot-mark">${escapeHtml(slotToken(slot, index))}</div>
            <div class="chip-row">
              ${slotStateChip(slot)}
              ${accessChip}
              ${planChip}
              ${authModeChip}
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
          </div>

          <div class="slot-facts">
            ${factRow("邮箱", info.email)}
            ${factRow("账号 ID", info.account_id)}
            ${factRow("最后刷新", formatDate(info.last_refresh))}
          </div>

          <details class="token-details">
            <summary class="token-summary">
              <span>查看认证详情</span>
              <span class="token-summary-note">${text(tokenSummaryText(info))}</span>
            </summary>
            <div class="token-body">
              <div class="token-grid">
                ${renderAuthDetailCards(info)}
              </div>
            </div>
          </details>

          <div class="slot-actions">
            <button
              class="button secondary"
              type="button"
              data-action="rename"
              data-slot-id="${encodedSlotId}"
              data-slot-label="${encodedDataValue(slot.label || accountDisplayTitle(slot))}">
              改名称
            </button>
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
          renderCurrent(state.current);
          renderWorkspace(state);
          renderSlotSummary(state);
          renderSlots(state);
          setSyncPill(providerMeta().label + " 状态已同步", "idle");
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

    async function renameSlot(slotId, currentLabel) {
      const nextLabel = window.prompt("给这个已保存账号起一个更容易识别的名字", currentLabel || "");
      if (nextLabel === null) {
        return;
      }

      const trimmed = nextLabel.trim();
      if (!trimmed) {
        throw new Error("名称不能为空");
      }
      if (trimmed === (currentLabel || "").trim()) {
        return;
      }

      await request(providerActionPath("/accounts/" + encodeSlotId(slotId) + "/rename"), {
        method: "POST",
        body: JSON.stringify({ label: trimmed })
      });
      flash("已更新账号名称");
      await refreshState({ quiet: true });
    }

    document.getElementById("refresh-button").addEventListener("click", () => {
      refreshState().catch(() => {});
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

      if (action === "rename") {
        const currentLabel = decodeURIComponent(button.dataset.slotLabel || "");
        button.disabled = true;
        renameSlot(slotId, currentLabel)
          .catch((error) => flash(error.message, true))
          .finally(() => {
            button.disabled = false;
          });
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

    document.addEventListener("visibilitychange", () => {
      if (!document.hidden) {
        refreshState({ quiet: true }).catch(() => {});
      }
    });

    window.setInterval(() => {
      if (!document.hidden) {
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
