import { createContext, useContext, useEffect, useState } from 'react';
import {
  createUserWithEmailAndPassword,
  signInWithEmailAndPassword,
  signInWithPopup,
  signOut,
  onAuthStateChanged,
  updateProfile,
} from 'firebase/auth';
import { auth, googleProvider, isFirebaseConfigured } from '../firebase';
import { upsertUserProfile } from '../services/firestoreService';

const AuthContext = createContext(null);

export const AuthProvider = ({ children }) => {
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true);
  const [authError, setAuthError] = useState(null);

  useEffect(() => {
    if (!auth) {
      setUser(null);
      setLoading(false);
      return;
    }

    const unsubscribe = onAuthStateChanged(auth, async (firebaseUser) => {
      setUser(firebaseUser);
      setLoading(false);

      if (firebaseUser) {
        try {
          await upsertUserProfile(firebaseUser);
        } catch (error) {
          console.error('Failed to sync user profile to Firestore:', error);
        }
      }
    });

    return unsubscribe;
  }, []);

  const loginWithEmail = async (email, password) => {
    setAuthError(null);
    if (!auth) {
      const error = new Error('Firebase is not configured. Add credentials to .env.local to enable sign-in.');
      setAuthError(error.message);
      throw error;
    }
    try {
      await signInWithEmailAndPassword(auth, email, password);
    } catch (error) {
      setAuthError(error.message);
      throw error;
    }
  };

  const registerWithEmail = async (email, password, displayName = '') => {
    setAuthError(null);
    if (!auth) {
      const error = new Error('Firebase is not configured. Add credentials to .env.local to enable sign-in.');
      setAuthError(error.message);
      throw error;
    }
    try {
      const credential = await createUserWithEmailAndPassword(auth, email, password);
      if (displayName) {
        await updateProfile(credential.user, { displayName });
      }
    } catch (error) {
      setAuthError(error.message);
      throw error;
    }
  };

  const signInWithGoogle = async () => {
    setAuthError(null);
    if (!auth) {
      const error = new Error('Firebase is not configured. Add credentials to .env.local to enable sign-in.');
      setAuthError(error.message);
      throw error;
    }
    try {
      await signInWithPopup(auth, googleProvider);
    } catch (error) {
      setAuthError(error.message);
      throw error;
    }
  };

  const logout = async () => {
    if (!auth) return;
    await signOut(auth);
  };

  return (
    <AuthContext.Provider
      value={{
        user,
        loading,
        authError,
        isFirebaseConfigured,
        loginWithEmail,
        registerWithEmail,
        signInWithGoogle,
        logout,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
};

export const useAuth = () => {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error('useAuth must be used within an AuthProvider');
  }
  return context;
};
