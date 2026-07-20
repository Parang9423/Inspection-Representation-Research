import AppFolderFirst from './AppFolderFirst'
import ScanStatusBanner from './ScanStatusBanner'

export default function App() {
  return (
    <>
      <div className="global-scan-status"><ScanStatusBanner /></div>
      <AppFolderFirst />
    </>
  )
}
