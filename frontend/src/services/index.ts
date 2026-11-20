import { config } from '../config';
import { MockService } from './mock';
import { HttpService } from './http';
export const mock = new MockService();
export const service = config.mode === 'mock' ? mock : new HttpService();
