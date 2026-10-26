import {
  ButtonItem,
  Navigation,
  PanelSection,
  PanelSectionRow,
  Spinner,
  staticClasses,
} from "@decky/ui";
import { callable, definePlugin, toaster } from "@decky/api";
import { useEffect, useState } from "react";
import { FaStethoscope } from "react-icons/fa";

// Steam's own client objects, available in Gaming Mode's UI.
declare const SteamClient: any;
declare const appStore: any;

type Fix = {
  action: "verify_files" | "set_proton" | "open_protondb" | "move_plugin" | "open_decky_store" | "open_decky_settings";
  label: string;
  tool: string | null;
  target: string | null;
};
type Finding = {
  id: string;
  severity: "problem" | "warning" | "info";
  title: string;
  detail: string;
  evidence: string | null;
  fixes: Fix[];
};
type Report = {
  appid: number;
  last_launch: { start: string; seconds: number | null; proton: string | null } | null;
  forced_tool: string | null;
  undo_tool: string | null;
  logs_checked: string[];
  findings: Finding[];
};
type RecentGame = { appid: number; seconds: number | null; start: string };
type HealthReport = {
  decky_version: string | null;
  latest_version: string | null;
  plugin_count: number;
  findings: Finding[];
};

const recentGames = callable<[], RecentGame[]>("recent_games");
const checkup = callable<[appid: number], Report>("checkup");
const rememberTool = callable<[appid: number, previous: string], void>("remember_tool");
const forgetTool = callable<[appid: number], void>("forget_tool");
const pluginHealth = callable<[], HealthReport>("plugin_health");
const movePlugin = callable<[folder: string], string>("move_plugin");

const SEVERITY_ICON = { problem: "🔴", warning: "🟡", info: "🔵" };

const REPO = "https://github.com/Forlarin/deck-doctor";
// Findings with a step-by-step page in docs/fixes/ (kept in sync by tests/test_guides.py).
const GUIDES = new Set([
  "anticheat_blocked", "anticheat_error", "corrupt_files", "decky_outdated", "duplicate_plugin",
  "gpu_device_lost", "low_disk", "missing_dotnet", "missing_vcredist", "not_fully_installed",
  "plugin_crashed", "quick_exit", "trainer_new_proton", "unbuilt_plugin",
]);

function openWeb(url: string) {
  Navigation.NavigateToExternalWeb(url);
  Navigation.CloseSideMenus();
}

/** Open a pre-filled GitHub issue with what Deck Doctor found, for the person to review and send. */
function askForHelp(subject: string, context: string[], findings: Finding[]) {
  const problems = findings.filter((f) => f.severity !== "info");
  const lines = [
    "**What Deck Doctor showed**",
    ...context,
    ...problems.flatMap((f) => [`- ${f.title}`, ...(f.evidence ? [`  \`${f.evidence}\``] : [])]),
    "",
    "**What I tried**",
    "",
    "",
    "**Anything else**",
    "",
  ];
  const title = problems.length ? `${subject}: ${problems[0].title}` : subject;
  openWeb(`${REPO}/issues/new?labels=help&title=${encodeURIComponent(title)}&body=${encodeURIComponent(lines.join("\n"))}`);
}

function HelpButton({ onClick }: { onClick: () => void }) {
  return (
    <PanelSectionRow>
      <ButtonItem layout="below" onClick={onClick}>
        Still stuck? Get help
      </ButtonItem>
    </PanelSectionRow>
  );
}

// Non-Steam shortcuts (emulators, Heroic games) get IDs above 2^31 and have no ProtonDB page.
const isSteamGame = (appid: number) => appid < 2 ** 31;

function gameName(appid: number): string {
  return appStore?.GetAppOverviewByAppID?.(appid)?.display_name ?? `App ${appid}`;
}

function verifyFiles(appid: number) {
  if (typeof SteamClient?.Apps?.VerifyApp === "function") {
    SteamClient.Apps.VerifyApp(appid);
  } else {
    SteamClient.URL.ExecuteSteamURL(`steam://validate/${appid}`);
  }
  toaster.toast({
    title: "Deck Doctor",
    body: "Steam is checking the game's files. Progress shows in Downloads.",
  });
}

async function setProton(report: Report, tool: string) {
  await rememberTool(report.appid, report.forced_tool ?? "");
  SteamClient.Apps.SpecifyCompatTool(report.appid, tool);
  toaster.toast({ title: "Deck Doctor", body: `Switched to ${tool}. Launch the game to try it.` });
}

async function undoProton(report: Report) {
  SteamClient.Apps.SpecifyCompatTool(report.appid, report.undo_tool ?? "");
  await forgetTool(report.appid);
  toaster.toast({ title: "Deck Doctor", body: "Restored the game's original Proton setting." });
}

function openDeckyPage(path: "/decky/store" | "/decky/settings") {
  Navigation.Navigate(path);
  Navigation.CloseSideMenus();
}

function FindingView({ finding, fixes, onFix }: { finding: Finding; fixes: Fix[]; onFix: (fix: Fix) => void }) {
  return (
    <>
      <PanelSectionRow>
        <div style={{ fontWeight: "bold" }}>
          {SEVERITY_ICON[finding.severity]} {finding.title}
        </div>
        <div style={{ fontSize: "12px", marginTop: "4px", lineHeight: 1.4 }}>{finding.detail}</div>
        {finding.evidence && (
          <div style={{ fontSize: "11px", marginTop: "4px", opacity: 0.6, wordBreak: "break-word" }}>
            {finding.evidence}
          </div>
        )}
      </PanelSectionRow>
      {fixes.map((fix) => (
        <PanelSectionRow key={fix.label}>
          <ButtonItem layout="below" onClick={() => onFix(fix)}>
            {fix.label}
          </ButtonItem>
        </PanelSectionRow>
      ))}
      {GUIDES.has(finding.id) && (
        <PanelSectionRow>
          <ButtonItem layout="below" onClick={() => openWeb(`${REPO}/blob/main/docs/fixes/${finding.id}.md`)}>
            How to fix this (step by step)
          </ButtonItem>
        </PanelSectionRow>
      )}
    </>
  );
}

let lastHealth: HealthReport | null = null;

function PluginHealth() {
  const [health, setHealthState] = useState<HealthReport | null>(lastHealth);
  const [busy, setBusy] = useState(false);

  const run = async () => {
    setBusy(true);
    try {
      lastHealth = await pluginHealth();
      setHealthState(lastHealth);
    } finally {
      setBusy(false);
    }
  };

  const onFix = async (fix: Fix) => {
    if (fix.action === "open_decky_store") openDeckyPage("/decky/store");
    if (fix.action === "open_decky_settings") openDeckyPage("/decky/settings");
    if (fix.action === "move_plugin" && fix.target) {
      const dest = await movePlugin(fix.target);
      toaster.toast({
        title: "Deck Doctor",
        body: `Moved "${fix.target}" to ${dest.replace(/^\/home\/[^/]+/, "~")}. Restart the Deck to finish.`,
      });
      run();
    }
  };

  return (
    <PanelSection title="Plugin health">
      {health?.findings.map((f) => (
        <FindingView key={f.id + f.title} finding={f} fixes={f.fixes} onFix={onFix} />
      ))}
      {health?.findings.some((f) => f.severity !== "info") && (
        <HelpButton
          onClick={() =>
            askForHelp("Plugin problem", [`Decky ${health.decky_version ?? "?"}, ${health.plugin_count} plugins`], health.findings)
          }
        />
      )}
      <PanelSectionRow>
        <ButtonItem layout="below" disabled={busy} onClick={run}>
          {busy ? "Checking…" : health ? "Check plugins again" : "Check plugins"}
        </ButtonItem>
      </PanelSectionRow>
    </PanelSection>
  );
}

// Decky remounts the panel whenever the Quick Access menu closes and reopens,
// so the last report is kept outside React state to survive that.
let lastReport: Report | null = null;

function GameCheck() {
  const [games, setGames] = useState<RecentGame[] | null>(null);
  const [report, setReportState] = useState<Report | null>(lastReport);
  const [busyId, setBusyId] = useState<number | null>(null);

  const setReport = (r: Report | null) => {
    lastReport = r;
    setReportState(r);
  };

  useEffect(() => {
    recentGames().then(setGames);
  }, []);

  const runCheckup = async (id: number) => {
    setBusyId(id);
    try {
      setReport(await checkup(id));
    } finally {
      setBusyId(null);
    }
  };

  const runGameFix = async (r: Report, fix: Fix) => {
    if (fix.action === "verify_files") verifyFiles(r.appid);
    if (fix.action === "open_protondb") openWeb(`https://www.protondb.com/app/${r.appid}`);
    if (fix.action === "set_proton" && fix.tool) {
      await setProton(r, fix.tool);
      runCheckup(r.appid);
    }
  };

  if (games === null) {
    return (
      <PanelSection>
        <PanelSectionRow>
          <Spinner />
        </PanelSectionRow>
      </PanelSection>
    );
  }

  if (!games.length) {
    return (
      <PanelSection title="Game won't launch?">
        <PanelSectionRow>
          <div style={{ fontSize: "12px" }}>
            Launch the game once (even if it fails), then come back here to check it.
          </div>
        </PanelSectionRow>
      </PanelSection>
    );
  }

  const gameList = (
      <PanelSection title={report ? "Check another game" : "Game won't launch? Pick it to check"}>
        {games.map((g) => (
          <PanelSectionRow key={g.appid}>
            <ButtonItem
              layout="below"
              disabled={busyId !== null}
              onClick={() => runCheckup(g.appid)}
            >
              {busyId === g.appid ? "Checking…" : gameName(g.appid)}
              {report?.appid === g.appid && busyId === null ? " ✓" : ""}
            </ButtonItem>
          </PanelSectionRow>
        ))}
      </PanelSection>
  );

  // Results go first so they're visible without scrolling past the game list.
  return (
    <>
      {report && (
        <PanelSection title={gameName(report.appid)}>
          {report.last_launch && (
            <PanelSectionRow>
              <div style={{ fontSize: "11px", opacity: 0.7 }}>
                Last launch {report.last_launch.start}
                {report.last_launch.seconds != null && ` · ran ${Math.round(report.last_launch.seconds)}s`}
                {report.last_launch.proton && ` · ${report.last_launch.proton}`}
                {report.logs_checked.length > 0 && ` · read ${report.logs_checked.length} log file(s)`}
              </div>
            </PanelSectionRow>
          )}
          {report.findings.map((f) => (
            <FindingView
              key={f.id}
              finding={f}
              fixes={f.fixes.filter((x) => x.action !== "open_protondb" || isSteamGame(report.appid))}
              onFix={(fix) => runGameFix(report, fix)}
            />
          ))}
          {report.undo_tool !== null && (
            <PanelSectionRow>
              <ButtonItem
                layout="below"
                onClick={async () => {
                  await undoProton(report);
                  runCheckup(report.appid);
                }}
              >
                Undo Deck Doctor's Proton change
              </ButtonItem>
            </PanelSectionRow>
          )}
          {report.findings.some((f) => f.severity !== "info") && (
            <HelpButton
              onClick={() =>
                askForHelp(gameName(report.appid), [
                  `Game: ${gameName(report.appid)} (${report.appid})`,
                  report.last_launch
                    ? `Last launch: ran ${Math.round(report.last_launch.seconds ?? 0)}s on ${report.last_launch.proton ?? "native/shortcut"}`
                    : "No recent launch",
                ], report.findings)
              }
            />
          )}
        </PanelSection>
      )}
      {gameList}
    </>
  );
}

function Content() {
  return (
    <>
      <GameCheck />
      <PluginHealth />
    </>
  );
}

export default definePlugin(() => ({
  name: "Deck Doctor",
  titleView: <div className={staticClasses.Title}>Deck Doctor</div>,
  content: <Content />,
  icon: <FaStethoscope />,
}));
