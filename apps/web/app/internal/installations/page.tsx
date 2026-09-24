type RepositorySummary = { full_name: string; is_active: boolean };
type InstallationSummary = {
  account_login: string | null;
  account_type: string | null;
  github_installation_id: number;
  repository_count: number;
  repositories: RepositorySummary[];
};

async function fetchInstallations(): Promise<
  { ok: true; data: InstallationSummary[] } | { ok: false; error: string }
> {
  const secret = process.env.CODENTRY_INTERNAL_WEBHOOK_SECRET;
  const baseUrl = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

  if (!secret) {
    return { ok: false, error: "CODENTRY_INTERNAL_WEBHOOK_SECRET is not configured" };
  }

  try {
    const response = await fetch(`${baseUrl}/internal/installations`, {
      headers: { "X-Codentry-Internal-Secret": secret },
      cache: "no-store",
    });
    if (!response.ok) {
      console.error(JSON.stringify({ logger: "codentry.web.installations", status: response.status }));
      return { ok: false, error: "the backend rejected the request" };
    }
    return { ok: true, data: await response.json() };
  } catch (err) {
    const message = err instanceof Error ? err.message : "unknown error";
    console.error(JSON.stringify({ logger: "codentry.web.installations", error: message }));
    return { ok: false, error: "the backend could not be reached" };
  }
}

export const dynamic = "force-dynamic";

// Internal debugging view for the project team only — NOT the product's
// future user dashboard (see PRD FR-8: any real dashboard is optional and
// secondary). Access is enforced by middleware.ts: the route 404s unless
// INTERNAL_PAGES_ENABLED=true and then requires HTTP Basic auth
// (INTERNAL_PAGES_USER / INTERNAL_PAGES_PASSWORD). See lib/internal-access.ts.
export default async function InternalInstallationsPage() {
  const result = await fetchInstallations();

  return (
    <main>
      <h1>Installations (internal debug view)</h1>
      <p>
        For the Codentry team only. Not a product surface — see PRD FR-8. Protected by HTTP Basic
        auth (see middleware.ts); do not link to this page publicly.
      </p>

      {!result.ok ? (
        <p>Could not load installations: {result.error}. Details are in the server log.</p>
      ) : result.data.length === 0 ? (
        <p>No installations recorded yet.</p>
      ) : (
        <table>
          <thead>
            <tr>
              <th>Account</th>
              <th>Type</th>
              <th>Installation ID</th>
              <th>Repositories</th>
            </tr>
          </thead>
          <tbody>
            {result.data.map((installation) => (
              <tr key={installation.github_installation_id}>
                <td>{installation.account_login ?? "(unknown — no installation event seen yet)"}</td>
                <td>{installation.account_type ?? "—"}</td>
                <td>{installation.github_installation_id}</td>
                <td>
                  <ul>
                    {installation.repositories.map((repo) => (
                      <li key={repo.full_name}>
                        {repo.full_name} — {repo.is_active ? "active" : "inactive"}
                      </li>
                    ))}
                  </ul>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </main>
  );
}
