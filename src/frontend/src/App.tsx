import { createBrowserRouter, Navigate, RouterProvider } from 'react-router-dom';
import PrivateRoute from '@/components/auth/PrivateRoute';
import PublicRoute from '@/components/auth/PublicRoute';
import AppShell from '@/components/layout/AppShell';
import DashboardPage from '@/pages/DashboardPage';
import DocumentListPage from '@/pages/documents/DocumentListPage';
import UploadPage from '@/pages/documents/UploadPage';
import DocumentDetailPage from '@/pages/documents/DocumentDetailPage';
import ChatPage from '@/pages/ChatPage';
import GlobalRagChatPage from '@/pages/GlobalRagChatPage';
import StrategistPage from '@/pages/StrategistPage';
import LoginPage from '@/pages/LoginPage';
import RegisterPage from '@/pages/RegisterPage';
import MonitoringDocumentPicker from '@/pages/MonitoringDocumentPicker';
import MonitoringPage from '@/pages/MonitoringPage';

const router = createBrowserRouter([
  {
    path: '/',
    element: <Navigate to="/dashboard" replace />,
  },
  {
    element: <PublicRoute />,
    children: [
      { path: '/login', element: <LoginPage /> },
      { path: '/register', element: <RegisterPage /> },
    ],
  },
  {
    element: <PrivateRoute />,
    children: [
      // Chat routes — outside AppShell (no container padding)
      { path: '/documents/:documentId/chat', element: <ChatPage /> },
      { path: '/documents/:documentId/chat/:conversationId', element: <ChatPage /> },
      // Global RAG / Legal Research routes — outside AppShell
      { path: '/legal-research', element: <GlobalRagChatPage /> },
      { path: '/legal-research/:conversationId', element: <GlobalRagChatPage /> },
      // Strategist routes — outside AppShell
      { path: '/strategist', element: <StrategistPage /> },
      { path: '/strategist/:conversationId', element: <StrategistPage /> },
      // Monitoring routes — outside AppShell (full-height layout)
      { path: '/monitoring', element: <MonitoringDocumentPicker /> },
      { path: '/monitoring/:documentId', element: <MonitoringPage /> },
      // AppShell routes (with container padding)
      {
        element: <AppShell />,
        children: [
          { path: '/dashboard', element: <DashboardPage /> },
          { path: '/documents', element: <DocumentListPage /> },
          { path: '/documents/upload', element: <UploadPage /> },
          { path: '/documents/:documentId', element: <DocumentDetailPage /> },
        ],
      },
    ],
  },
  {
    path: '*',
    element: <Navigate to="/dashboard" replace />,
  },
]);

export default function App() {
  return <RouterProvider router={router} />;
}
