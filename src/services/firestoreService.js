import { doc, setDoc, deleteDoc, collection, getDocs, serverTimestamp } from 'firebase/firestore';
import { db } from '../firebase';

export const upsertUserProfile = async (user) => {
  const userRef = doc(db, 'users', user.uid);
  await setDoc(
    userRef,
    {
      email: user.email,
      displayName: user.displayName || null,
      photoURL: user.photoURL || null,
      lastLoginAt: serverTimestamp(),
    },
    { merge: true }
  );
};

export const saveDocumentMetadata = async (userId, docData) => {
  const docId = docData.doc_id || docData.id || crypto.randomUUID();
  const docRef = doc(db, 'users', userId, 'documents', String(docId));
  await setDoc(docRef, {
    filename: docData.name,
    type: docData.type,
    status: docData.status,
    uploadedAt: docData.uploadDate,
    backendDocId: docData.doc_id || null,
    originalName: docData.name,
    metadata: docData.metadata || {},
    updatedAt: serverTimestamp(),
  });
  return docId;
};

export const deleteDocumentMetadata = async (userId, docId) => {
  const docRef = doc(db, 'users', userId, 'documents', String(docId));
  await deleteDoc(docRef);
};

export const getUserDocuments = async (userId) => {
  const docsRef = collection(db, 'users', userId, 'documents');
  const snapshot = await getDocs(docsRef);
  return snapshot.docs.map((entry) => {
    const data = entry.data();
    return {
      id: entry.id,
      doc_id: data.backendDocId || entry.id,
      name: data.originalName || data.filename,
      type: data.type,
      status: data.status,
      uploadDate: data.uploadedAt || '',
      metadata: data.metadata || {},
    };
  });
};

export const saveUserSession = async (userId, sessionData) => {
  const sessionRef = doc(collection(db, 'users', userId, 'sessions'), sessionData.session_id);
  await setDoc(sessionRef, {
    ...sessionData,
    updatedAt: serverTimestamp(),
  });
};

export const saveChatMessage = async (userId, sessionId, role, text) => {
  const messageRef = doc(collection(db, 'users', userId, 'sessions', sessionId, 'messages'));
  await setDoc(messageRef, {
    role,
    text,
    createdAt: serverTimestamp(),
  });
};
