export type SplitCode='unassigned'|'train'|'valid'|'test'
export type StatusCode='included'|'review'|'excluded'
export interface ImageItem{image_id:string;filename:string;source_label:string;label:string;split:SplitCode;status:StatusCode;note:string;image_url:string;cam_url:string;[key:string]:unknown}
export interface Summary{totals:Record<string,number>;classes:Array<{label:string;train:number;valid:number;test:number;unassigned:number;total:number}>}
