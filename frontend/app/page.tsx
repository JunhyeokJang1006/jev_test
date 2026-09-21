export const dynamic = "force-dynamic";

import CampaignPanel from "./campaign";

async function backendAvailable(): Promise<boolean> {
  try {
    const base = process.env.BACKEND_URL ?? "http://127.0.0.1:8000";
    const response = await fetch(`${base}/api/health`, {
      cache: "no-store",
      signal: AbortSignal.timeout(2000),
    });
    if (!response.ok) return false;
    const health = await response.json();
    return health.status === "ok" && health.service === "luna-realms-api";
  } catch {
    return false;
  }
}

export default async function Home() {
  const connected = await backendAvailable();
  return (
    <main>
      <p className="eyebrow">LUNA REALMS / GREYHAVEN</p>
      <h1>도난당한 왕실 봉인</h1>
      <p>비 내리는 여관에서 시작된 사건. 단서를 따라가고, 누구를 믿을지 결정하세요.</p>
      <section aria-label="개발 상태">
        <h2>캠페인 연결</h2>
        <p data-testid="backend-status">API 연결: {connected ? "정상" : "연결 대기"}</p>
        <p>행동을 선택하거나 직접 입력하세요. 중요한 선택 전에는 저장할 수 있습니다.</p>
      </section>
      <CampaignPanel />
      <p className="note">서버 실행 후 새로고침하면 연결 상태를 다시 확인합니다.</p>
    </main>
  );
}
