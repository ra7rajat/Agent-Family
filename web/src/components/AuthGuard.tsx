"use client";

import { useAuth } from "../context/AuthContext";
import SignInPrompt from "./SignInPrompt";

interface Props {
  children: React.ReactNode;
}

export default function AuthGuard({ children }: Props) {
  const { user, loading } = useAuth();

  if (loading) {
    return (
      <div className="auth-loading" role="status" aria-label="Checking authentication…">
        <div className="spinner" aria-hidden="true" />
      </div>
    );
  }

  if (!user) {
    return <SignInPrompt />;
  }

  return <>{children}</>;
}
