import { AppHeader } from '@/components/app-header'
import { AssessPage } from '@/features/assess/assess-page'
import { RequirementsPage } from '@/features/requirements/requirements-page'
import { useRoute } from '@/lib/use-route'

export default function App() {
  const [route, navigate] = useRoute()
  return (
    <>
      <AppHeader route={route} onNavigate={navigate} />
      {route === 'requirements' ? <RequirementsPage /> : <AssessPage />}
    </>
  )
}
