import { AppHeader } from '@/components/app-header'
import { Toaster } from '@/components/ui/sonner'
import { AssessPage } from '@/features/assess/assess-page'
import { HomePage } from '@/features/home/home-page'
import { RequirementsPage } from '@/features/requirements/requirements-page'
import { useRoute } from '@/lib/use-route'

export default function App() {
  const [route, navigate] = useRoute()
  return (
    <>
      <AppHeader route={route} onNavigate={navigate} />
      {route === 'home' && <HomePage onNavigate={navigate} />}
      {route === 'requirements' && <RequirementsPage />}
      {route === 'assess' && <AssessPage />}
      <Toaster />
    </>
  )
}
