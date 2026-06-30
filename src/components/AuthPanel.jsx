import { useState } from 'react';
import { useAuth } from '../context/AuthContext';

const AuthPanel = () => {
  const { loginWithEmail, registerWithEmail, signInWithGoogle, authError, isFirebaseConfigured } = useAuth();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [mode, setMode] = useState('login');
  const [message, setMessage] = useState('');

  const handleSubmit = async (event) => {
    event.preventDefault();
    setMessage('');
    try {
      if (mode === 'login') {
        await loginWithEmail(email, password);
        setMessage('Signed in successfully.');
      } else {
        await registerWithEmail(email, password);
        setMessage('Account created successfully.');
      }
    } catch (error) {
      setMessage(error.message || 'Authentication failed.');
    }
  };

  return (
    <div className="mx-auto max-w-md rounded-[2rem] border border-slate-200 bg-white p-8 shadow-soft">
      <div className="mb-6 text-center">
        <h1 className="text-2xl font-semibold text-slate-900">Welcome to Procure.ai</h1>
        <p className="mt-2 text-sm text-slate-500">Sign in to analyze spreadsheets, manage RFQs, and store results in Firebase.</p>
      </div>
      {!isFirebaseConfigured && (
        <div className="mb-4 rounded-3xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900">
          Firebase Web App config is incomplete. Copy values from Firebase Console (Project Settings → Your apps → Web app) into <code className="font-mono">.env</code>. Project number <strong>717267585384</strong> belongs in <code className="font-mono">VITE_FIREBASE_MESSAGING_SENDER_ID</code>.
        </div>
      )}
      <div className="grid gap-3">
        <button
          type="button"
          onClick={signInWithGoogle}
          className="inline-flex items-center justify-center gap-2 rounded-3xl border border-slate-200 bg-white px-4 py-3 text-sm font-semibold text-slate-700 shadow-sm hover:bg-slate-50 transition"
        >
          <span>Continue with Google</span>
        </button>
        <div className="relative text-center text-xs uppercase tracking-[0.24em] text-slate-400">or</div>
        <form onSubmit={handleSubmit} className="grid gap-4">
          <input
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder="Email"
            className="w-full rounded-3xl border border-slate-200 px-4 py-3 text-sm focus:outline-none focus:ring-2 focus:ring-sky-500"
            required
          />
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            placeholder="Password"
            className="w-full rounded-3xl border border-slate-200 px-4 py-3 text-sm focus:outline-none focus:ring-2 focus:ring-sky-500"
            required
          />
          <button type="submit" className="rounded-3xl bg-sky-600 px-4 py-3 text-sm font-semibold text-white hover:bg-sky-700 transition">
            {mode === 'login' ? 'Sign in' : 'Create account'}
          </button>
        </form>
        <button
          type="button"
          onClick={() => setMode(mode === 'login' ? 'register' : 'login')}
          className="mt-2 text-sm font-medium text-slate-600 hover:text-slate-900"
        >
          {mode === 'login' ? 'New here? Create an account' : 'Already have an account? Sign in'}
        </button>
        <div className="rounded-3xl border border-rose-100 bg-rose-50 px-4 py-3 text-sm text-rose-700">
          {authError || message}
        </div>
      </div>
    </div>
  );
};

export default AuthPanel;
