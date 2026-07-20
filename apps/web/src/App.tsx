import AppFolderFirst from './AppFolderFirst'
import ScanStatusBanner from './ScanStatusBanner'
import './scan-status.css'

export default function App() {
  return (
    <>
      <div className="global-scan-status"><ScanStatusBanner /></div>
      <AppFolderFirst />
    </>
  )
}
