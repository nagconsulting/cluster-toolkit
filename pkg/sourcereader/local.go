// Copyright 2022 Google LLC
//
// Licensed under the Apache License, Version 2.0 (the "License");
// you may not use this file except in compliance with the License.
// You may obtain a copy of the License at
//
//      http://www.apache.org/licenses/LICENSE-2.0
//
// Unless required by applicable law or agreed to in writing, software
// distributed under the License is distributed on an "AS IS" BASIS,
// WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
// See the License for the specific language governing permissions and
// limitations under the License.

package sourcereader

import (
	"fmt"
	"hpc-toolkit/pkg/resreader"
	"os"
)

// LocalSourceReader reads modules from a local directory
type LocalSourceReader struct{}

// GetModuleInfo gets resreader.ModuleInfo for the given kind from the local source
func (r LocalSourceReader) GetModuleInfo(modPath string, kind string) (resreader.ModuleInfo, error) {
	if !IsLocalPath(modPath) {
		return resreader.ModuleInfo{}, fmt.Errorf("Source is not valid: %s", modPath)
	}

	reader := resreader.Factory(kind)
	return reader.GetInfo(modPath)
}

// GetModule copies the local source to a provided destination (the deployment directory)
func (r LocalSourceReader) GetModule(modPath string, copyPath string) error {
	if !IsLocalPath(modPath) {
		return fmt.Errorf("Source is not valid: %s", modPath)
	}

	if _, err := os.Stat(modPath); os.IsNotExist(err) {
		return fmt.Errorf("Local module doesn't exist at %s", modPath)
	}

	return copyFromPath(modPath, copyPath)
}
