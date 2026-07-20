import axios from 'axios'
import type{ImageItem,SplitCode,StatusCode,Summary}from'../types'
export const api=axios.create({baseURL:'/api'})
export async function fetchImages(params:Record<string,unknown>){return(await api.get<{items:ImageItem[];total:number}>('/images',{params})).data}
export async function fetchSummary(){return(await api.get<Summary>('/summary')).data}
export async function bulkUpdate(payload:{image_ids:string[];label?:string;split?:SplitCode;status?:StatusCode;note?:string}){return(await api.patch('/images/bulk',payload)).data}
export async function autoSplit(payload:{train_ratio:number;valid_ratio:number;test_ratio:number;seed:number;only_unassigned:boolean}){return(await api.post('/splits/auto',payload)).data}
export async function exportDataset(payload:{dataset_name:string;mode:'copy'|'hardlink'|'manifest'}){return(await api.post('/exports',payload)).data}
export async function scanDataset(){return(await api.post('/scan')).data}
