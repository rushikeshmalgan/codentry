type SetupPageProps = {
  searchParams: Promise<{ installation_id?: string; setup_action?: string }>;
};

// GitHub redirects here after a user installs or configures the App. This
// page is purely informational — it does NOT write any bookkeeping itself.
// Installation/repository rows are created asynchronously by the
// `installation` webhook event (see app/api/github/webhook/route.ts and
// services/ai-review/app/events.py), which is the durable source of truth,
// not this page's query params.
export default async function SetupPage({ searchParams }: SetupPageProps) {
  const params = await searchParams;
  const justInstalled = Boolean(params.installation_id);

  return (
    <main>
      <h1>Codentry for GitHub</h1>

      {justInstalled ? (
        <p>
          <strong>Installation received.</strong> Codentry will begin reviewing pull requests on
          the repositories you selected shortly. You can close this tab.
        </p>
      ) : (
        <p>
          Codentry is a GitHub App that automatically reviews pull requests by combining
          deterministic static analysis (ESLint, Semgrep) with AI judgment (Claude) — and posts
          findings directly as comments on the pull request itself. There is no separate
          dashboard you need to check.
        </p>
      )}

      <h2>What installing Codentry does</h2>
      <ul>
        <li>Every pull request opened, updated, or reopened on a selected repository is reviewed automatically.</li>
        <li>Findings are posted as comments on the pull request — nothing to install locally, nothing else to configure.</li>
        <li>Codentry never approves, merges, or modifies code. A human always makes that decision.</li>
      </ul>

      <h2>Permissions Codentry requests</h2>
      <ul>
        <li><strong>Pull requests:</strong> Read &amp; write — to read PR content and post review comments.</li>
        <li><strong>Contents:</strong> Read-only — to fetch the files changed in a PR.</li>
        <li><strong>Metadata:</strong> Read-only — required by GitHub for every App.</li>
      </ul>
      <p>
        Codentry does not request Administration, Actions, or any permission that could merge a
        PR or modify repository settings — it is structurally unable to do either, regardless of
        what any review comment says.
      </p>

      <h2>Turning Codentry off for a repository</h2>
      <p>
        Uninstalling the App (or removing a repository from the installation in GitHub&apos;s own
        settings) stops future reviews for that repository. Past review history is kept, not
        deleted — repositories are marked inactive rather than removed.
      </p>
    </main>
  );
}
