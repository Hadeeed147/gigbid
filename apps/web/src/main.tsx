import { StrictMode, type ReactNode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { AnalyticsPage } from "./app/analytics/AnalyticsPage";
import { InboxPage } from "./app/inbox/InboxPage";
import { JobPage } from "./app/jobs/JobPage";
import { LoginPage } from "./app/login/LoginPage";
import { MessagesPage } from "./app/messages/MessagesPage";
import { OnboardingPage } from "./app/onboarding/OnboardingPage";
import { PipelinePage } from "./app/pipeline/PipelinePage";
import { RunPage } from "./app/runs/RunPage";
import { SettingsPage } from "./app/settings/SettingsPage";
import { StudioPage } from "./app/studio/StudioPage";
import { AppShell } from "./components/AppShell";
import { Loading } from "./components/States";
import { AuthProvider, useAuth } from "./lib/auth";
import "./styles.css";

function RequireAuth({ children, onboarded = true }: { children: ReactNode; onboarded?: boolean }) {
  const { user, loading } = useAuth();
  if (loading) return <Loading label="Signing you in" />;
  if (!user) return <Navigate to="/login" replace />;
  if (onboarded && !user.onboarded) return <Navigate to="/onboarding" replace />;
  return <>{children}</>;
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <AuthProvider>
      <BrowserRouter>
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          <Route
            path="/onboarding"
            element={
              <RequireAuth onboarded={false}>
                <OnboardingPage />
              </RequireAuth>
            }
          />
          <Route
            element={
              <RequireAuth>
                <AppShell />
              </RequireAuth>
            }
          >
            <Route path="/inbox" element={<InboxPage />} />
            <Route path="/jobs/:id" element={<JobPage />} />
            <Route path="/studio/:id" element={<StudioPage />} />
            <Route path="/pipeline" element={<PipelinePage />} />
            <Route path="/messages" element={<MessagesPage />} />
            <Route path="/messages/:threadId" element={<MessagesPage />} />
            <Route path="/runs/:id" element={<RunPage />} />
            <Route path="/analytics" element={<AnalyticsPage />} />
            <Route path="/settings" element={<SettingsPage />} />
          </Route>
          <Route path="*" element={<Navigate to="/inbox" replace />} />
        </Routes>
      </BrowserRouter>
    </AuthProvider>
  </StrictMode>,
);
