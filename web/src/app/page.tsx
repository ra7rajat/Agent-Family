"use client";

import AuthGuard from "../components/AuthGuard";
import ChatInterface from "../components/ChatInterface";
import { useAuth } from "../context/AuthContext";

function UserHeader() {
  const { user, signOut } = useAuth();
  if (!user) return null;
  return (
    <div className="user-header">
      {user.picture ? (
        // eslint-disable-next-line @next/next/no-img-element
        <img
          src={user.picture}
          alt={user.name ?? user.email ?? "User"}
          className="user-avatar"
          width={28}
          height={28}
        />
      ) : (
        <div className="user-avatar-fallback" aria-hidden="true">
          {(user.name ?? user.email ?? "U")[0].toUpperCase()}
        </div>
      )}
      <span className="user-email">{user.name ?? user.email}</span>
      <button className="signout-btn" onClick={signOut} aria-label="Sign out">
        Sign out
      </button>
    </div>
  );
}

export default function Home() {
  return (
    <main className="app-container">
      <header className="header">
        <h1>Agent Family</h1>
        <UserHeader />
      </header>
      <AuthGuard>
        <ChatInterface />
      </AuthGuard>
    </main>
  );
}
